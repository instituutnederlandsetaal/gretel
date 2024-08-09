from functools import partial
from typing import Callable, Iterable, List, Optional, TypeVar, cast

from rest_framework.response import Response
from rest_framework.decorators import (
    api_view,
    parser_classes,
    renderer_classes,
    authentication_classes,
)
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework import status
from django.conf import settings
from lxml import etree

from treebanks.models import Component, BaseXDB
from treebanks.access import available_treebanks
from .models import SearchQuery
from .basex_search import (
    generate_xquery_showtree,
    generate_xquery_metadata_count,
    parse_metadata_count_result,
)
from .tasks import run_search_query
from .types import Result, ResultSet
from services.basex import basex

from mwe_query import analyze_mwe_hit
from mwe_query.canonicalform import expandfull

import logging

log = logging.getLogger(__name__)


def _get_components(component_slugs, treebank):
    """Only search components registered with the requested Django treebank."""
    return Component.objects.filter(slug__in=component_slugs, treebank__slug=treebank)


T = TypeVar("T")


def format_multi_mwe_attr(items: List[T], selector: Callable[[T], str]) -> str:
    values = set(selector(item) for item in items)
    return ";".join(sorted(values))


def parent(node: etree._Element) -> Optional[etree._Element]:
    nodes = node.xpath("parent::node")
    if nodes == []:
        result = None
    else:
        result = nodes[0]
    return result


def common_node_parent(node1: etree._Element, node2: etree._Element) -> etree._Element:
    """Goes up both nodes until a common parent is found

    Args:
        node1 (etree._Element): node to match
        node2 (etree._Element): node to match

    Raises:
        ValueError: no common parent found, nodes aren't in the same tree

    Returns:
        etree._Element: the common parent node
    """
    # go up nodes until a common parent is found
    node1parent = node1
    while True:
        node2parent = node2
        while True:
            if node1parent == node2parent:
                return node1parent
            node2parent = parent(node2parent)
            if node2parent is None:
                break

        node1parent = parent(node1parent)
        if node1parent is None:
            break

    raise ValueError(
        "No common parent found, this should not be possible if they are in the same tree!"
    )


def common_node_parent_multiple(nodes: List[etree._Element]) -> etree._Element:
    if len(nodes) == 0:
        raise ValueError("Empty list")

    if len(nodes) == 1:
        return nodes[0]

    parent = nodes[0]
    for i in range(1, len(nodes)):
        parent = common_node_parent(parent, nodes[i])

    return parent


def add_mwe_attributes(queries: List[str], result: Result):
    xpath_predicates = " or ".join(f"@begin={begin}" for begin in result.begins)
    xpath = f"//node[{xpath_predicates}]"
    tree = cast(etree._ElementTree, result.tree)
    nodes = cast(List[etree._Element], tree.xpath(xpath))
    if nodes:
        hit = common_node_parent_multiple(nodes)
        hit_info = analyze_mwe_hit(hit, queries, result.tree)
        result.attributes.update(
            {
                "mwe_arguments_heads_fringe": format_multi_mwe_attr(
                    hit_info.arguments.heads, lambda head: head.fringe
                ),
                "mwe_arguments_heads_hdword": format_multi_mwe_attr(
                    hit_info.arguments.heads, lambda head: head.hdword
                ),
                "mwe_arguments_heads_hdlemma": format_multi_mwe_attr(
                    hit_info.arguments.heads, lambda head: head.hdlemma
                ),
                "mwe_arguments_heads_rel": format_multi_mwe_attr(
                    hit_info.arguments.heads, lambda head: head.rel
                ),
                "mwe_arguments_frame": hit_info.arguments.frame.frame_str,
                "mwe_arguments_rel_cats_fringe": format_multi_mwe_attr(
                    hit_info.arguments.rel_cats, lambda rel_cat: rel_cat.fringe
                ),
                "mwe_arguments_rel_cats_poscat": format_multi_mwe_attr(
                    hit_info.arguments.rel_cats, lambda rel_cat: rel_cat.poscat
                ),
                "mwe_arguments_rel_cats_rel": format_multi_mwe_attr(
                    hit_info.arguments.rel_cats, lambda rel_cat: rel_cat.rel
                ),
                "mwe_components_lemma_parts": hit_info.components.lemma_parts,
                "mwe_components_word_parts": hit_info.components.word_parts,
                "mwe_components_marked_utt": hit_info.components.marked_utt,
                "mwe_determinations_comp_lemma": format_multi_mwe_attr(
                    hit_info.determinations,
                    lambda determination: determination.comp_lemma,
                ),
                "mwe_determinations_fringe": format_multi_mwe_attr(
                    hit_info.determinations, lambda determination: determination.fringe
                ),
                "mwe_determinations_head_lemma": format_multi_mwe_attr(
                    hit_info.determinations,
                    lambda determination: determination.head_lemma,
                ),
                "mwe_determinations_head_pos_cat": format_multi_mwe_attr(
                    hit_info.determinations,
                    lambda determination: determination.head_pos_cat,
                ),
                "mwe_determinations_head_word": format_multi_mwe_attr(
                    hit_info.determinations,
                    lambda determination: determination.head_word,
                ),
                "mwe_determinations_node_cat": format_multi_mwe_attr(
                    hit_info.determinations,
                    lambda determination: determination.node_cat,
                ),
                "mwe_determinations_node_rel": format_multi_mwe_attr(
                    hit_info.determinations,
                    lambda determination: determination.node_rel,
                ),
                "mwe_modifications_comp_lemma": format_multi_mwe_attr(
                    hit_info.modifications, lambda modification: modification.comp_lemma
                ),
                "mwe_modifications_fringe": format_multi_mwe_attr(
                    hit_info.modifications, lambda modification: modification.fringe
                ),
                "mwe_modifications_head_lemma": format_multi_mwe_attr(
                    hit_info.modifications, lambda modification: modification.head_lemma
                ),
                "mwe_modifications_head_pos_cat": format_multi_mwe_attr(
                    hit_info.modifications,
                    lambda modification: modification.head_pos_cat,
                ),
                "mwe_modifications_head_word": format_multi_mwe_attr(
                    hit_info.modifications, lambda modification: modification.head_word
                ),
                "mwe_modifications_node_cat": format_multi_mwe_attr(
                    hit_info.modifications, lambda modification: modification.node_cat
                ),
                "mwe_modifications_node_rel": format_multi_mwe_attr(
                    hit_info.modifications, lambda modification: modification.node_rel
                ),
            }
        )


def mwe_include(queries: List[str]) -> Callable[[ResultSet], ResultSet]:
    def analyze_rows(rows: Iterable[Result]):
        for row in rows:
            add_mwe_attributes(queries, row)
            yield row

    return analyze_rows


def filter_expand(results: ResultSet) -> ResultSet:
    for result in results:
        try:
            result.tree = expandfull(result.tree)
        except Exception:
            log.exception("Failed expanding index nodes for sentence")
        yield result


def filter_include(xpath: str, results: ResultSet) -> ResultSet:
    for result in results:
        if result.tree.xpath(xpath):
            yield result


def filter_exclude(xpath: str, results: ResultSet) -> ResultSet:
    for result in results:
        if result.tree.xpath(xpath):
            continue
        else:
            yield result


@api_view(["POST"])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer])
@parser_classes([JSONParser])
def search_view(request):  # noqa: C901
    data = request.data
    try:
        xpath = data["xpath"]
        treebank = data["treebank"]
        component_slugs = data["components"]
    except KeyError as err:
        return Response(
            {"error": "{} is missing".format(err)}, status=status.HTTP_400_BAD_REQUEST
        )
    query_id = data.get("query_id", None)
    is_analysis = data.get("is_analysis", False)
    variables = data.get("variables", [])
    behaviour = data.get("behaviour", {})
    available = available_treebanks(request.user)
    if not available.filter(pk=treebank).exists():
        return Response({'error': 'Treebank not found.'}, status=status.HTTP_404_NOT_FOUND)

    if is_analysis:
        maximum_results = settings.MAXIMUM_RESULTS_ANALYSIS
    else:
        maximum_results = settings.MAXIMUM_RESULTS

    # The frontend might ask us to run the given query on the results of
    # another "superset" query instead of directly on BaseX.
    # in that case, a separate 'supersetXpath' variable is set, which we then
    # place in the normal 'xpath' variable because that's what BaseX knows
    # about.

    use_superset = behaviour.get("supersetXpath") is not None

    should_expand_index = behaviour.get("expandIndex", False)
    mwe_queries: List[str] = behaviour.get("mweQueries", [])

    if use_superset:
        subset_xpath = xpath
        xpath = behaviour["supersetXpath"]

    if query_id:
        new_query = False
        try:
            # We also require the right XPath to avoid the possibility of
            # tampering with queries of other users.
            # TODO: also check if the component list is correct
            query = SearchQuery.objects.get(pk=query_id)
            if query.components.exclude(treebank__in=available).exists():
                return Response({'error': 'Query not found.'}, status=status.HTTP_404_NOT_FOUND)
        except SearchQuery.DoesNotExist:
            return Response(
                {"error": "Cannot find given query_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        new_query = True
        component_objects = _get_components(component_slugs, treebank)
        if component_objects.count() != len(component_slugs):
            return Response(
                {"error": "Not all requested components could be found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        query = SearchQuery(xpath=xpath, variables=variables)
        query.save()
        query.components.add(*component_objects)
        query.initialize()

    if should_expand_index:
        query.add_filter(filter_expand)

    if mwe_queries:
        query.add_filter(mwe_include(mwe_queries))

    if use_superset:
        query.add_filter(partial(filter_include, subset_xpath))

    for exclusion_xpath in behaviour.get("exclusions", []):
        query.add_filter(partial(filter_exclude, exclusion_xpath))

    if new_query:
        try:
            run_search_query.delay(query.pk)
        except run_search_query.OperationalError:
            # No connection with message broker - run synchronously
            run_search_query.apply((query.pk,))

    # Get results so far, if any.
    # We store the ids of returned results in the request session,
    # in order to deduplicate results by id.
    session_key = f"returned_{query.pk}"
    returned = set(request.session.get(session_key, []))
    maximum_results = max(0, maximum_results - len(returned))
    results, percentage, counts = query.get_results(maximum_results, exclude=returned)
    returned |= set(r.id for r in results)
    request.session[session_key] = list(returned)

    if data.get("retrieveContext"):
        results = query.augment_with_context(results)

    # serialize results
    results = [result.as_dict() for result in results]

    if request.accepted_renderer.format == "api":
        # If using the API view, only show part of the results, because
        # the HTML rendering of Django Rest Framework turns out to be
        # very slow
        results = (
            str(results)[0:5000] + "… (remainder hidden because of slow rendering)"
        )
    response = {
        "query_id": query.id,
        "search_percentage": percentage,
        "results": results,
        "counts": counts,
    }
    if percentage == 100:
        response["errors"] = query.get_errors()
    if query.cancelled is True:
        response["cancelled"] = True

    return Response(response)


@api_view(["POST"])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer])
@parser_classes([JSONParser])
def cancel_query_view(request):
    data = request.data
    try:
        xpath = data["xpath"]
        query_id = data["query_id"]
    except KeyError as err:
        return Response(
            {"error": "{} is missing".format(err)}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # We also require the right XPath to avoid the possibility of
        # tampering with queries of other users.
        # TODO: also check if the component list is correct
        query = SearchQuery.objects.get(xpath=xpath, pk=query_id)
        if query.components.exclude(treebank__in=available_treebanks(request.user)).exists():
            return Response({'error': 'Query not found.'}, status=status.HTTP_404_NOT_FOUND)
    except SearchQuery.DoesNotExist:
        return Response(
            {"error": "Cannot find given query_id"}, status=status.HTTP_400_BAD_REQUEST
        )
    query.cancel_search()


@api_view(["POST"])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer])
@parser_classes([JSONParser])
def tree_view(request):
    data = request.data
    try:
        database = data["database"]
        sentence_id = data["sentence_id"]
    except KeyError as err:
        return Response(
            {"error": "{} is missing".format(err)}, status=status.HTTP_400_BAD_REQUEST
        )
    try:
        xquery = generate_xquery_showtree(database, sentence_id)
    except ValueError as err:
        return Response({"error": str(err)}, status=status.HTTP_400_BAD_REQUEST)
    if not BaseXDB.objects.filter(
        pk=database, component__treebank__in=available_treebanks(request.user)
    ).exists():
        return Response({'error': 'Treebank not found.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        result = basex.perform_query(xquery)
    except OSError as err:
        return Response(
            {"error": str(err)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    return Response({"tree": result})


@api_view(["POST"])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer])
@parser_classes([JSONParser])
def metadata_count_view(request):
    data = request.data
    try:
        xpath = data["xpath"]
        treebank = data["treebank"]
        components = data["components"]
    except KeyError as err:
        return Response(
            {"error": "{} is missing".format(err)}, status=status.HTTP_400_BAD_REQUEST
        )
    if not available_treebanks(request.user).filter(pk=treebank).exists():
        return Response({'error': 'Treebank not found.'}, status=status.HTTP_404_NOT_FOUND)
    xml_pieces = []
    for component_slug in components:
        try:
            component = Component.objects.get(slug=component_slug, treebank__slug=treebank)
        except Component.DoesNotExist:
            return Response({'error': 'Component not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not component.treebank.metadata:
            continue
        dbs = component.get_databases().keys()
        for db in dbs:
            xquery = generate_xquery_metadata_count(db, xpath)
            try:
                xml_count_for_db = basex.perform_query(xquery)
            except OSError as err:
                return Response(
                    {"error": "BaseX search error"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
                log.error("Error in metadata count view: {}".format(err))
            if xml_count_for_db == "<metadata/>":
                continue
            xml_pieces.append(
                xml_count_for_db.replace("<metadata>", "").replace("</metadata>", "")
            )
    xml = "<metadata>" + "".join(xml_pieces) + "</metadata>"
    counts = parse_metadata_count_result(xml)
    return Response(counts)

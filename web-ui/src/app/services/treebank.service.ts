import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';

import { BehaviorSubject, Observable, ReplaySubject, EMPTY, firstValueFrom, lastValueFrom } from 'rxjs';
import { mergeMap, catchError, shareReplay, map, first } from 'rxjs/operators';

import {
    ComponentGroup,
    FuzzyNumber,
    Treebank,
    TreebankComponent,
    TreebankComponents,
    TreebankDetails,
    TreebankMetadata
} from '../treebank';
import { ConfigurationService } from './configuration.service';
import { NotificationService } from './notification.service';

/**
 * Dummy component which is used to mark that a component is missing
 * and should always be disabled and unselectable
 */
export const MISSING_COMPONENT_ID = '#MISSING#';

export interface TreebankLookup {
    providers: { name: string, corpora: Set<string> }[];
    data: {
        [provider: string]: {
            [corpus: string]: Treebank;
        }
    };
}
export interface DjangoTreebankResponse {
    slug: string;
    title: string;
    description: string;
    url_more_info: string;
    is_public?: boolean;
    groups?: {
        slug: string;
        description: string
    }[];
    variants?: string[];
}

interface DjangoTreebankMetadataResponse {
    field: string;
    type: 'text' | 'int' | 'date';
    facet: 'checkbox' | 'slider' | 'range';
    min_value: string | null;
    max_value: string | null;
}

export interface DjangoComponentsForTreebankResponse {
    slug: string;
    title: string;
    description: string;
    nr_sentences: string;
    nr_words: string;
    group?: string;
    variant?: string;
}

class LazyRetrieve<T> {
    value?: Promise<T | undefined>;
    get(): Promise<T | undefined> {
        return this.value || (this.value = this.retriever()
            .catch((reason: HttpErrorResponse) => {
                NotificationService.addError(reason);
                return undefined;
            }));
    }

    constructor(private retriever: () => Promise<T>) {
        this.get = this.get.bind(this);
    }
}

abstract class TreebankBase implements Treebank {
    provider: string; id: string;
    displayName: string;
    description?: string;
    multiOption: boolean;
    isPublic: boolean;
    userId?: number;
    email?: string;
    uploaded?: Date;
    processed?: Date;
    details: { [T in keyof TreebankDetails]: () => Promise<TreebankDetails[T] | undefined> };
}

class LazyTreebank extends TreebankBase {
    constructor(
        values: Omit<Treebank, 'details'>,
        retrievers: {
            [T in keyof Treebank['details']]: Treebank['details'][T]
        }) {
        super();
        Object.assign(this, values);

        this.details = {
            metadata: new LazyRetrieve(retrievers.metadata).get,
            components: new LazyRetrieve(retrievers.components).get,
            componentGroups: new LazyRetrieve(retrievers.componentGroups).get,
            variants: new LazyRetrieve(retrievers.variants).get
        };
    }
}

export class ReadyTreebank extends TreebankBase {
    constructor(
        values: Omit<Treebank, 'details'>,
        details: TreebankDetails) {
        super();
        Object.assign(this, values);

        this.details = {
            metadata: () => Promise.resolve(details.metadata),
            components: () => Promise.resolve(details.components),
            componentGroups: () => Promise.resolve(details.componentGroups),
            variants: () => Promise.resolve(details.variants)
        };
    }
}

function makeDjangoMetadata(item: DjangoTreebankMetadataResponse): TreebankMetadata {
    const metadata: TreebankMetadata = {
        field: item.field,
        type: item.type,
        facet: item.facet,
        show: true
    }

    if (['slider', 'range'].includes(metadata.facet)) {
        switch (metadata.type) {
            case 'int':
                metadata.minValue = parseInt(item.min_value, 10);
                metadata.maxValue = parseInt(item.max_value, 10);
                return metadata;
            case 'date':
                metadata.minValue = new Date(item.min_value);
                metadata.maxValue = new Date(item.max_value);
                return metadata;
        }
    }

    return metadata;
}

function makeDjangoComponent(comp: DjangoComponentsForTreebankResponse): TreebankComponent {
    return {
        description: comp.description,
        disabled: false,
        id: comp.slug,
        sentenceCount: parseInt(comp.nr_sentences, 10),
        title: comp.title,
        wordCount: parseInt(comp.nr_words, 10),

        group: comp.group,
        variant: comp.variant,
    }
}

function makeDjangoTreebank(bank: DjangoTreebankResponse): Omit<Treebank, 'details'> {
    return {
        id: bank.slug,
        displayName: bank.title,
        description: bank.description,
        isPublic: bank.is_public ?? true,
        multiOption: true,
        provider: 'gretel',
    }
}

@Injectable()
export class TreebankService {
    /**
     * Use getTreebanks to start loading.
     * Some treebanks may become available here before it is done.
     */
    public readonly treebanks = new BehaviorSubject<TreebankLookup>({ providers: [], data: {} });

    private treebanksLoader: Promise<void>;

    constructor(private configurationService: ConfigurationService, private http: HttpClient) {
    }

    public async get(provider: string, corpus: string) {
        const get = (treebankLookup: TreebankLookup) => {
            const treebanks = treebankLookup.data[provider];
            return treebanks && treebanks[corpus];
        };

        const treebank = get(this.treebanks.value);
        if (treebank) {
            return treebank;
        }

        return firstValueFrom(
            this.getTreebanks() && this.treebanks.pipe(
                map(treebanks => get(treebanks)),
                first(treebank => !!treebank)));
    }

    /**
     * Completes when all providers have been queried.
     */
    public async getTreebanks(): Promise<TreebankLookup> {
        if (!this.treebanksLoader) {
            this.treebanksLoader = this.loadAll();
        }
        await this.treebanksLoader;
        return this.treebanks.value;
    }

    private async loadAll() {
        const allTreebanks$ = this.getDjangoTreebanks().pipe(shareReplay());
        allTreebanks$.subscribe((treebank) => {
            if (treebank) {
                const current = this.treebanks.value;
                const provider = current.providers.find(p => p.name === treebank.provider);
                if (provider) {
                    provider.corpora.add(treebank.id);
                } else {
                    current.providers.push({ name: treebank.provider, corpora: new Set([treebank.id]) });
                }
                this.treebanks.next({
                    providers: current.providers,
                    data: {
                        ...current.data,
                        [treebank.provider]: {
                            ...current.data[treebank.provider],
                            [treebank.id]: treebank
                        }
                    }
                });
            }
        });

        // Wait for completion even when no treebanks were returned.
        await lastValueFrom(allTreebanks$, { defaultValue: undefined });
    }

    private getDjangoTreebanks(): Observable<Treebank> {
        const ob = new ReplaySubject<Treebank>();

        // Not working with providers for now

        (async () => {
            const djangoUrl = await this.configurationService.getDjangoUrl('treebanks/treebank/');

            this.http.get<DjangoTreebankResponse[]>(djangoUrl, { withCredentials: true })
                .pipe(
                    mergeMap(r => r),
                    map(r => this.getDjangoTreebank(r)),
                    catchError((error: HttpErrorResponse) => {
                        NotificationService.addError(error);
                        return EMPTY;
                    })
                )
                .subscribe(ob);
        })();

        return ob;
    }

    private async getDjangoComponents(bank: DjangoTreebankResponse) {
        const url = await this.configurationService.getDjangoUrl('treebanks/treebank/' + bank.slug + '/components/');
        const djangoComponents = await firstValueFrom(this.http.get<DjangoComponentsForTreebankResponse[]>(url, { withCredentials: true }));

        const components: TreebankComponent[] = djangoComponents.map(makeDjangoComponent);
        return components.reduce<TreebankComponents>((cs, c) => { cs[c.id] = c; return cs; }, {});
    }

    private getDjangoTreebank(bank: DjangoTreebankResponse): Treebank {
        const components = new LazyRetrieve(async () => await this.getDjangoComponents(bank));
        return new LazyTreebank(
            makeDjangoTreebank(bank),
            {
                metadata: async () => {
                    const url = await this.configurationService.getDjangoUrl('treebanks/treebank/' + bank.slug + '/metadata/');
                    const { metadata } = await firstValueFrom(this.http.get<{ 'metadata': DjangoTreebankMetadataResponse[] }>(url, { withCredentials: true }));
                    return Array.isArray(metadata) ? metadata.map(makeDjangoMetadata) : [];
                },
                componentGroups: async () => {
                    // are the components grouped?
                    if (!Array.isArray(bank.groups) || !bank.groups.length) {
                        return undefined;
                    }

                    const groups: { [key: string]: ComponentGroup } = {};
                    for (const group of bank.groups) {
                        groups[group.slug] = {
                            components: {},
                            key: group.slug,
                            sentenceCount: new FuzzyNumber(0),
                            wordCount: new FuzzyNumber(0),
                            description: group.description,
                        };
                    }
                    for (const component of Object.values(await components.get() || {})) {
                        if (component.group) {
                            if (!groups[component.group]) {
                                groups[component.group] = {
                                    components: { [component.variant]: component.id },
                                    key: component.group,
                                    sentenceCount: new FuzzyNumber(component.sentenceCount),
                                    wordCount: new FuzzyNumber(component.wordCount),
                                    description: component.description
                                }
                            } else {
                                const group = groups[component.group];
                                group.components[component.variant] = component.id;
                                group.sentenceCount.add(component.sentenceCount);
                                group.wordCount.add(component.wordCount);
                            }
                        }
                    }

                    // add missing components for variants
                    if (Array.isArray(bank.variants) && bank.variants.length > 1) {
                        for (const group of bank.groups) {
                            for (const variant of bank.variants) {
                                if (!groups[group.slug].components[variant]) {
                                    groups[group.slug].components[variant] = MISSING_COMPONENT_ID;
                                }
                            }
                        }
                    }

                    return Object.values(groups).sort(
                        (a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
                },
                components: async () => { return await components.get(); },
                variants: async () => {
                    // should the components (also) be grouped by variant?
                    return Array.isArray(bank.variants) && bank.variants.length > 1 ? [...bank.variants] : undefined;
                },
            }
        )
    }
}

import { Component } from "@angular/core";
import { ActivatedRoute, Router } from "@angular/router";

type TreebankSelectionMap = {
    [provider: string]:
    {
        [corpus: string]: string[]
    }
};
/**
 * Rewrites GrETEL 4 address to GrETEL 5
 */
@Component({
    selector: 'grt-legacy-component',
    template: '<span>Rewriting address...</span>'
})
export class LegacyComponent {

    constructor(activatedRoute: ActivatedRoute, router: Router) {
        const segments = activatedRoute.snapshot.url;

        const queryParams = {
            ...activatedRoute.snapshot.queryParams
        };

        LegacyComponent.rewriteParams(queryParams);

        if (segments.length >= 1 && segments[0].path === 'ng') {
            router.navigate(segments.slice(1).map(segment => segment.path), {
                queryParams
            });
        }
    }

    /**
     * Rewrites the parameters in-place
     * @param queryParams parameters to rewrite
     */
    public static rewriteParams(queryParams: { [x: string]: any }): void {
        if (queryParams['selectedTreebanks']) {
            const selectedTreebanks = JSON.parse(queryParams.selectedTreebanks);
            queryParams['selectedTreebanks'] = JSON.stringify(LegacyComponent.rewriteComponentNames(selectedTreebanks));
        }
    }

    private static rewriteComponentNames(selection: TreebankSelectionMap) {
        const rules: {
            [path: string]: {
                corpusName: (name: string) => string,
                componentName: (name: string) => string
            }
        } = {
            'gretel/cgn': {
                corpusName: () => 'cgn',
                componentName: (name) => name.replace('CGN_ID_', 'cgn-').toLowerCase()
            },
            'gretel/lassy': {
                corpusName: () => 'lassy-klein',
                componentName: (name) => name.replace('LASSY_ID_', '').toLowerCase()
            }
        };

        const output: TreebankSelectionMap = {};
        for (const [provider, corpora] of Object.entries(selection)) {
            output[provider] = { ...corpora };
        }

        for (const [path, { corpusName, componentName }] of Object.entries(rules)) {
            const [matchProvider, matchCorpus] = path.split('/');
            const components = selection[matchProvider]?.[matchCorpus];
            if (components) {
                delete output[matchProvider][matchCorpus];
                // Sort the converted IDs to keep redirects predictable.
                output[matchProvider][corpusName(matchCorpus)] = components.map(componentName).sort();
            }
        }

        return output;
    }
}

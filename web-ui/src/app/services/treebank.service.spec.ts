import { HttpClient } from '@angular/common/http';
import { of } from 'rxjs';

import { ConfigurationService } from './configuration.service';
import { DjangoTreebankResponse, MISSING_COMPONENT_ID, TreebankService } from './treebank.service';

describe('TreebankService', () => {
    let service: TreebankService;
    let get: jasmine.Spy;
    let responses: { [url: string]: unknown };
    const bank: DjangoTreebankResponse = {
        slug: 'uploaded', title: 'Uploaded', description: '', url_more_info: '',
    };

    beforeEach(() => {
        responses = {
            'treebanks/treebank/': [bank],
            'treebanks/treebank/uploaded/components/': [],
            'treebanks/treebank/uploaded/metadata/': { metadata: [] },
        };
        get = jasmine.createSpy('get').and.callFake(url => of(responses[url]));
        service = new TreebankService(
            { getDjangoUrl: async path => path } as ConfigurationService,
            { get } as unknown as HttpClient,
        );
    });

    async function uploaded() {
        return (await service.getTreebanks()).data.gretel.uploaded;
    }

    it('completes discovery when the backend has no treebanks', async () => {
        responses['treebanks/treebank/'] = [];
        expect(await service.getTreebanks()).toEqual({ providers: [], data: {} });
    });

    it('preserves privacy and sends session credentials for all detail requests', async () => {
        responses['treebanks/treebank/'] = [{ ...bank, is_public: false }];
        const treebank = await uploaded();
        expect(treebank.isPublic).toBe(false);
        await treebank.details.components();
        await treebank.details.metadata();
        expect(get.calls.count()).toBe(3);
        get.calls.allArgs().forEach(args => expect(args[1]).toEqual({ withCredentials: true }));
    });

    it('supports declared groups with no components and missing variants', async () => {
        responses['treebanks/treebank/'] = [{
            ...bank, variants: ['NL', 'VL'],
            groups: [{ slug: 'main', description: 'Dataset' }, { slug: 'empty', description: 'Empty' }],
        }];
        responses['treebanks/treebank/uploaded/components/'] = [{
            slug: 'nl', title: 'Dutch', description: '', nr_sentences: 2, nr_words: 5,
            group: 'main', variant: 'NL',
        }];
        const groups = await (await uploaded()).details.componentGroups();
        expect(groups.map(group => group.key)).toEqual(['empty', 'main']);
        expect(groups[0].components).toEqual({ NL: MISSING_COMPONENT_ID, VL: MISSING_COMPONENT_ID });
        expect(groups[0].wordCount.value).toBe(0);
        expect(groups[1].components).toEqual({ NL: 'nl', VL: MISSING_COMPONENT_ID });
        expect(groups[1].description).toBe('Dataset');
        expect(groups[1].sentenceCount.value).toBe(2);
        expect(groups[1].wordCount.value).toBe(5);
    });

    it('supports variants without groups', async () => {
        responses['treebanks/treebank/'] = [{ ...bank, variants: ['NL', 'VL'], groups: [] }];
        const treebank = await uploaded();
        expect(await treebank.details.variants()).toEqual(['NL', 'VL']);
        expect(await treebank.details.componentGroups()).toBeUndefined();
    });

    it('builds variant placeholders for exactly one group', async () => {
        responses['treebanks/treebank/'] = [{
            ...bank, variants: ['NL', 'VL'], groups: [{ slug: 'main', description: 'Dataset' }],
        }];
        const groups = await (await uploaded()).details.componentGroups();
        expect(groups.length).toBe(1);
        expect(groups[0].components).toEqual({ NL: MISSING_COMPONENT_ID, VL: MISSING_COMPONENT_ID });
    });

    it('tolerates JSON string defaults produced by older imports', async () => {
        responses['treebanks/treebank/'] = [{ ...bank, variants: '[]', groups: '{}' }];
        responses['treebanks/treebank/uploaded/metadata/'] = { metadata: '[]' };
        const treebank = await uploaded();
        expect(await treebank.details.variants()).toBeUndefined();
        expect(await treebank.details.componentGroups()).toBeUndefined();
        expect(await treebank.details.metadata()).toEqual([]);
    });
});

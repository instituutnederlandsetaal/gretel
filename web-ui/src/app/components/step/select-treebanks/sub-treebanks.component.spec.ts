import { of } from 'rxjs';

import { SubTreebanksComponent } from './sub-treebanks.component';
import { TreebankSelectionService } from '../../../services/treebank-selection.service';
import { MISSING_COMPONENT_ID, ReadyTreebank } from '../../../services/treebank.service';
import { FuzzyNumber, TreebankComponent, TreebankDetails } from '../../../treebank';

describe('SubTreebanksComponent', () => {
    let component: SubTreebanksComponent;
    const first: TreebankComponent = {
        id: 'first', title: 'First', description: '', disabled: false,
        sentenceCount: 2, wordCount: 5, variant: 'NL',
    };

    beforeEach(() => {
        component = new SubTreebanksComponent({
            state$: of({ isSelected: () => false }),
        } as unknown as TreebankSelectionService);
    });
    afterEach(() => component.ngOnDestroy());

    async function load(details: Partial<TreebankDetails>) {
        component.treebank = new ReadyTreebank({
            multiOption: true, displayName: 'Uploaded', provider: 'gretel', id: 'uploaded', isPublic: true,
        }, { components: { first }, metadata: [], componentGroups: undefined, variants: undefined, ...details });
        await component.ngOnChanges({ treebank: {} as any });
    }

    it('calculates totals and selections for variants without groups', async () => {
        await load({ variants: ['NL', 'VL'] });
        expect(component.loading).toBe(false);
        expect(component.totalSentenceCountByVariant).toEqual({ NL: '2', VL: '0' });
        expect(component.totalWordCountByVariant).toEqual({ NL: '5', VL: '0' });
        expect(component.variants[0].selected).toBe(false);
        expect(component.components[MISSING_COMPONENT_ID]).toBeUndefined();
    });

    it('creates a disabled placeholder for a missing variant in a single group', async () => {
        await load({
            components: { first: { ...first, group: 'main' } }, variants: ['NL', 'VL'],
            componentGroups: [{
                key: 'main', components: { NL: 'first', VL: MISSING_COMPONENT_ID },
                sentenceCount: new FuzzyNumber(2), wordCount: new FuzzyNumber(5),
            }],
        });
        expect(component.components[MISSING_COMPONENT_ID].disabled).toBe(true);
        expect(component.totalSentenceCount).toBe('2');
        expect(component.totalWordCountByGroup).toEqual({ main: '5' });
    });

    it('counts components without group or variant metadata', async () => {
        await load({ components: { first: { ...first, variant: undefined } } });
        expect(component.totalSentenceCount).toBe('2');
        expect(component.totalWordCount).toBe('5');
        expect(component.totalSentenceCountByGroup).toEqual({});
        expect(component.totalSentenceCountByVariant).toEqual({});
    });
});

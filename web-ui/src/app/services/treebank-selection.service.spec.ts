import { TreebankSelectionService } from './treebank-selection.service';
import { ReadyTreebank, TreebankService } from './treebank.service';
import { StateService } from './state.service';
import { GlobalState, StepType } from '../pages/multi-step-page/steps';
import { TreebankSelection } from '../treebank';

describe('TreebankSelectionService variants', () => {
    it('toggles enabled components in a variant without requiring groups', async () => {
        const treebank = new ReadyTreebank({
            provider: 'gretel', id: 'uploaded', displayName: 'Uploaded', multiOption: true, isPublic: true,
        }, {
            components: {
                nl: { id: 'nl', title: '', description: '', disabled: false, sentenceCount: 1, wordCount: 2, variant: 'NL' },
                vl: { id: 'vl', title: '', description: '', disabled: false, sentenceCount: 1, wordCount: 2, variant: 'VL' },
                disabled: { id: 'disabled', title: '', description: '', disabled: true, sentenceCount: 0, wordCount: 0, variant: 'NL' },
            },
            variants: ['NL', 'VL'], componentGroups: undefined, metadata: [],
        });
        const treebankService = { get: async () => treebank } as unknown as TreebankService;
        const state = {
            selectedTreebanks: new TreebankSelection(treebankService),
            currentStep: { type: StepType.SelectTreebanks }, valid: false,
        } as GlobalState;
        const service = new TreebankSelectionService(treebankService, {
            updateState: update => update(state),
        } as unknown as StateService<GlobalState>);

        await service.toggleVariant('gretel', 'uploaded', 'NL');
        expect(state.selectedTreebanks.isSelected('gretel', 'uploaded', 'nl')).toBe(true);
        expect(state.selectedTreebanks.isSelected('gretel', 'uploaded', 'vl')).toBeFalsy();
        expect(state.selectedTreebanks.isSelected('gretel', 'uploaded', 'disabled')).toBeFalsy();
        expect(state.valid).toBe(true);

        await service.toggleVariant('gretel', 'uploaded', 'NL');
        expect(state.selectedTreebanks.isSelected('gretel', 'uploaded')).toBe(false);
        expect(state.valid).toBe(false);
    });
});

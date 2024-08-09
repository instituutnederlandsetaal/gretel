import { BehaviorSubject, EMPTY } from 'rxjs';
import { UploadComponent } from './upload.component';
import { User } from '../../services/user.service';

describe('UploadComponent', () => {
    let component: UploadComponent;
    let user: BehaviorSubject<User>;
    let uploads: any;

    beforeEach(() => {
        user = new BehaviorSubject<User>(undefined);
        uploads = jasmine.createSpyObj('UploadService', ['upload']);
        uploads.upload.and.returnValue(EMPTY);
        component = new UploadComponent({ add: jasmine.createSpy('add') } as any, uploads,
                                        { user$: user } as any);
    });

    it('asks anonymous visitors to sign in without starting an upload', () => {
        expect(component.canUpload).toBe(false);
        component.upload();
        expect(component.warning).toBe('Please sign in to upload a dataset.');
        expect(uploads.upload).not.toHaveBeenCalled();
    });

    it('allows a signed-in user to publish a public dataset', () => {
        user.next({ id: 1, username: 'admin', email: 'admin@example.org', display: 'admin' });
        component.file = new File(['content'], 'input.txt');
        component.isPublic = true;
        expect(component.canUpload).toBe(true);
        component.upload();
        expect(uploads.upload).toHaveBeenCalledWith(jasmine.objectContaining({ isPublic: true, file: component.file }));
    });

    it('closes the upload form again after logout', () => {
        user.next({ id: 1, username: 'admin', email: 'admin@example.org', display: 'admin' });
        expect(component.canUpload).toBe(true);
        user.next(undefined);
        expect(component.canUpload).toBe(false);
    });
});

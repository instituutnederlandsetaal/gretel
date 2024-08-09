import { HttpErrorResponse } from '@angular/common/http';
import { asyncScheduler, observeOn, of, throwError } from 'rxjs';
import { UserService } from './user.service';

describe('UserService registration settings', () => {
    async function createService(registrationEnabled = false, unavailable = false) {
        const http = jasmine.createSpyObj('HttpClient', ['get']);
        const notifications = jasmine.createSpyObj('NotificationService', ['add']);
        http.get.and.callFake((url: string) => {
            if (url === '/_allauth/browser/v1/config') {
                return unavailable
                    ? throwError(() => new HttpErrorResponse({ status: 503 })).pipe(observeOn(asyncScheduler))
                    : of({ status: 200, data: { account: { is_open_for_signup: registrationEnabled } } });
            }
            return of({ status: 401 });
        });
        const service = new UserService(http, { getDjangoUrl: async path => '/' + path } as any, notifications);
        await new Promise(resolve => setTimeout(resolve, 10));
        return { service, http, notifications };
    }

    it('keeps registration closed when configuration loading fails', async () => {
        const { service, notifications } = await createService(false, true);
        expect(service.registrationEnabled$.value).toBe(false);
        expect(notifications.add).toHaveBeenCalledWith('Could not load registration settings.', 'error');
    });

    it('reads enabled registration from the existing allauth configuration endpoint', async () => {
        const { service, http } = await createService(true);
        expect(service.registrationEnabled$.value).toBe(true);
        expect(http.get).toHaveBeenCalledWith('/_allauth/browser/v1/config');
    });

    it('keeps registration closed when allauth reports signup is disabled', async () => {
        const { service } = await createService(false);
        expect(service.registrationEnabled$.value).toBe(false);
    });
});

import { ElementRef } from '@angular/core';
import { FormBuilder } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { LoginStatusComponent } from './login-status.component';

describe('LoginStatusComponent', () => {
    let component: LoginStatusComponent;
    let registrationEnabled: BehaviorSubject<boolean>;
    let userService: any;
    let notifications: any;

    beforeEach(() => {
        registrationEnabled = new BehaviorSubject(false);
        userService = { registrationEnabled$: registrationEnabled, signup: jasmine.createSpy('signup').and.returnValue(Promise.resolve(false)) };
        notifications = jasmine.createSpyObj('NotificationService', ['add']);
        component = new LoginStatusComponent(new ElementRef({}), new FormBuilder(), userService, notifications);
        component.signupForm.setValue({ username: 'user', email: 'user@example.org', password: 'password', password2: 'password' });
    });

    it('blocks registration when the backend closes signup', async () => {
        expect(component.registrationEnabled).toBe(false);
        await component.signup();
        expect(userService.signup).not.toHaveBeenCalled();
    });

    it('does not announce success or clear the form when signup is rejected', async () => {
        registrationEnabled.next(true);
        await component.signup();
        expect(userService.signup).toHaveBeenCalled();
        expect(component.signupForm.value.email).toBe('user@example.org');
        expect(notifications.add).not.toHaveBeenCalled();
        expect(component.loading).toBe(false);
    });

    it('allows signup after it is enabled and resets the form after success', async () => {
        registrationEnabled.next(true);
        userService.signup.and.returnValue(Promise.resolve(true));
        await component.signup();
        expect(component.signupForm.value.email).toBeNull();
        expect(notifications.add).toHaveBeenCalledWith('Account created', 'success');
    });
});

import { Component, ElementRef, HostListener, OnDestroy, OnInit } from '@angular/core';
import { FormBuilder, FormControl, Validators } from '@angular/forms';
import { faUser, faUsers } from '@fortawesome/free-solid-svg-icons';
import { Subscription } from 'rxjs';
import { NotificationService } from '../../../../services/notification.service';
import { User, UserService } from '../../../../services/user.service';

@Component({
    selector: 'grt-login-status',
    templateUrl: './login-status.component.html',
    styleUrls: ['./login-status.component.scss']
})
export class LoginStatusComponent implements OnInit, OnDestroy {
    faUser = faUser;
    faUsers = faUsers;

    subscriptions: Subscription[] = [];

    /**
     * show the drop down menu
     */
    active = false;
    loading = false;

    user: User | null = null;
    
    mode = 'login' as 'login' | 'register' | 'resetPassword';

    loginForm = this.formBuilder.group({
        email: new FormControl('', {validators: [Validators.email, Validators.required]}),
        password: new FormControl('', {validators: [Validators.required]})
    });
    
    signupForm = this.formBuilder.group({
        username: new FormControl('', {validators: [Validators.required]}),
        email: new FormControl('', {validators: [Validators.email, Validators.required]}),
        password: new FormControl('', {validators: [Validators.required]}),
        password2: new FormControl('', {validators: [Validators.required, control => control.value !== control.parent?.get('password').value ? {passwordMatch: true} : null]})
    });

    verifyEmailForm = this.formBuilder.group({
        code: new FormControl('', {validators: [Validators.required]})
    });

    requestResetPasswordForm = this.formBuilder.group({
        email: new FormControl('', {validators: [Validators.email, Validators.required]})
    });

    performResetPasswordForm = this.formBuilder.group({
        code: new FormControl('', {validators: [Validators.required]}),
        password: new FormControl('', {validators: [Validators.required]}),
        password2: new FormControl('', {validators: [Validators.required, control => control.value !== control.parent?.get('password').value ? {passwordMatch: true} : null]})
    });

    constructor(private elementRef: ElementRef,
        private formBuilder: FormBuilder,
        private userService: UserService,
        private notificationService: NotificationService) { }

    getErrorMessage(key: string, value: any) {
        switch (key) {
            case 'required': return 'This field is required';
            case 'email': return 'Please enter a valid email address';
            case 'passwordMatch': return 'Passwords do not match';
            default: return `Unknown error ${key}`;
        }
    }

    ngOnInit(): void {
        this.subscriptions.push(this.userService.user$.subscribe(user => this.user = user))
    }

    ngOnDestroy(): void {
        for (let subscription of this.subscriptions) {
            subscription.unsubscribe();
        }
    }

    @HostListener('document:click', ['$event'])
    clickOutside(event: Event) {
        if (!this.elementRef.nativeElement.contains(event.target)) {
            this.active = false;
        }
    }

    toggleActive(event: Event) {
        this.active = !this.active;
        if (this.active) {
            // notifications overlap the menu
            this.notificationService.cancelAll()
        }
        event.stopPropagation();
        event.preventDefault();
        return false // cancel the click event
    }

    async signup() {
        if (this.signupForm.valid && !this.loading) {
            this.loading = true;
            if (this.userService.signup(this.signupForm.value.username, this.signupForm.value.email, this.signupForm.value.password)) {
                this.signupForm.reset();
                this.notificationService.add('Account created', 'success');
            }
            this.loading = false;
        }
    }

    async verifyEmail() {
        if (this.verifyEmailForm.valid && !this.loading) {
            this.loading = true;
            if (await this.userService.verify_email(this.verifyEmailForm.value.code)) {
                this.notificationService.add('Email verified', 'success');
                this.mode = 'login';
                this.verifyEmailForm.reset();
            }
            this.loading = false;
        }
    }

    async login() {
       if (this.loginForm.valid && !this.loading) {
            this.loading = true;
            if (await this.userService.login(this.loginForm.value.email, this.loginForm.value.password)) {
                this.loginForm.reset();
                this.notificationService.add('Logged in', 'success');
                this.active = false;
            }
            this.loading = false;
        }
    }

    async logout() {
        if (!this.loading) {
            this.loading = true;
            if (await this.userService.logout()) {
                this.notificationService.add('Logged out', 'success');
            }
    
            this.active = false;
            this.loading = false;
        }
    }

    async requestResetPassword() {
        if (this.requestResetPasswordForm.valid && !this.loading) {
            this.loading = true;
            const success = await this.userService.password_reset_request(this.requestResetPasswordForm.value.email);
            if (success) {
                this.notificationService.add('Password reset requested. Check your email', 'success');
            }
            this.loading = false;
        }
    }

    async performResetPassword() {
        if (this.performResetPasswordForm.valid && !this.loading) {
            this.loading = true;
            if (await this.userService.password_reset(this.performResetPasswordForm.value.code, this.performResetPasswordForm.value.password)) {
                this.notificationService.add('Password reset', 'success');
                this.mode = 'login';
            } 
            this.loading = false;
        }
    }
}

import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { BehaviorSubject, catchError, map, of, OperatorFunction, firstValueFrom } from 'rxjs';
import { ConfigurationService } from './configuration.service';
import { NotificationService } from './notification.service';

// NOTE: these urls do not end in a slash
const urls = {
    get_status: '_allauth/browser/v1/auth/session',
    login: '_allauth/browser/v1/auth/login',
    logout: '_allauth/browser/v1/auth/session',
    signup: '_allauth/browser/v1/auth/signup',
    password_reset_request: '_allauth/browser/v1/auth/password/request',
    password_reset: '_allauth/browser/v1/auth/password/reset',
    verify_email: '_allauth/browser/v1/auth/email/verify',
    config: '_allauth/browser/v1/config',
}

export type User = {
    id: number;
    display: string;
    email: string;
    username: string;
}

type BaseResponse = {
    status: number;
    data?: any;
    errors?: any;
}

type ConfigResponse = BaseResponse & {
    data: {
        account: { is_open_for_signup: boolean };
    };
}

type LoginResponse = BaseResponse&{
    status: 200,
    data: {
        user: User,
        // methods: any // the login method, unused by us.
    },
    meta: {
        session_token: string,
        access_token: string,
        is_authenticated: true
    }
}

type ErrorResponse = {
    status: number;
    errors?: Array<{message: string, code: string, param: string}>;
}

/**
 * Map http codes to handlers
 * - true -> return true, indicating success
 * - string -> print error message, return false
 * - function -> call function with response, return result
 */
type ReturnBinder<T> = {
    /** Action to take for specific response code. */
    [httpcode: number]: true|string|(<R extends T = T>(t: R) => boolean|string);
    /** Action on unknown response codes. */
    default: true|string|(<R extends T = T>(t: R) => boolean|string);
    /** Message to show on network error. */
    network_error?: string;
}

@Injectable({
    providedIn: 'root'
})
export class UserService {
    private _user$ = new BehaviorSubject<User>(undefined);
    private _token$ = new BehaviorSubject<LoginResponse['meta']>(undefined);
    private _registrationEnabled$ = new BehaviorSubject(false);

    constructor(
        private http: HttpClient,
        private configurationService: ConfigurationService,
        private notificationService: NotificationService
    ) {
        this.get_status();
        this.get_registration_config();
    }

    public get user$() {
        return this._user$;
    }

    public get registrationEnabled$() {
        return this._registrationEnabled$;
    }

    private async get_registration_config(): Promise<void> {
        try {
            const config = await firstValueFrom(this.http.get<ConfigResponse>(
                await this.configurationService.getDjangoUrl(urls.config)
            ));
            this._registrationEnabled$.next(config.data.account.is_open_for_signup);
        } catch {
            this.notificationService.add('Could not load registration settings.', 'error');
        }
    }

    /**
     * Check the http code and take the appropriate action.
     * If the code corresponds to a message, show it and return false.
     * If the code corresponds to a function, call it and return the result.
     * If the code corresponds to true, return true.
     * If the code is not found, perform the above for the 'default' action.
     *
     * True or false is returned to indicate whether the response should be considered successful.
     */
    private _handleResponse<T extends BaseResponse>(response: HttpErrorResponse|T, errorMap: ReturnBinder<T>): boolean {
        let httpResponse: BaseResponse;
        let httpCode: number;

        if (response instanceof HttpErrorResponse) {
            if (response.status === 0) { // network error
                this.notificationService.add(errorMap.network_error ?? 'Network error', 'error');
                return false;
            }
            // else it's a server error, i.e. non-200 response.
            httpResponse = response.error;
            httpCode = response.status;
        } else {
            // it's a normal response
            httpResponse = response;
            httpCode = response.status;
        }

        const action = errorMap[httpCode] ?? errorMap.default;
        if (action === true) return true;
        else if (typeof action === 'string') {
            this.notificationService.add(action, 'error');
            return false;
        } else if (typeof action === 'function') {
            const r = action(httpResponse as any); // assume callee knows the real type
            if (typeof r === 'string') {
                this.notificationService.add(r, 'error');
                return false;
            } else {
                return !!r;
            }
        } else {
            this.notificationService.add('Unknown error', 'error');
            return false;
        }
    }

    /**
     * Little helper to call _handleResponse on any event from the http stream.
     * allAuth tends to return valid responses with non-200 status codes.
     * Angular exposes those as an error, so we need to handle them.
     */
    private handleResponse<T extends BaseResponse>(binder: ReturnBinder<T>): OperatorFunction<T, boolean> {
        return (stream) => stream.pipe(
            map(response => this._handleResponse(response, binder)),
            catchError(error => of(this._handleResponse(error, binder)))
        )
    }

    /** Get the current signin status. Uses the browser session to retrieve info. */
    private async get_status(): Promise<boolean> {
        return this.http.get<LoginResponse>(await this.configurationService.getDjangoUrl(urls.get_status))
            .pipe(this.handleResponse({
                200: status => {
                    this._user$.next(status.data.user);
                    this._token$.next(status.meta);
                    return true;
                },
                401: true,
                default: 'Unknown error'
            }))
            .toPromise()
    }

    public async login(email: string, password: string): Promise<boolean> {
        return this.http.post<LoginResponse>(await this.configurationService.getDjangoUrl(urls.login), {email, password})
            .pipe(this.handleResponse({
                200: status => {
                    this._user$.next(status.data.user);
                    this._token$.next(status.meta);
                    return true;
                },
                401: 'Invalid login',
                default: (r: ErrorResponse) => r.errors?.map(e => e.message).join(', '),
            }))
            .toPromise()
    }

    public async logout(): Promise<boolean> {
        return this.http.delete(await this.configurationService.getDjangoUrl(urls.logout))
            .pipe(this.handleResponse({
                401: r => { // returns 401 when logged out...
                    this._user$.next(undefined);
                    this._token$.next(undefined);
                    return true;
                },
                default: 'Unknown error'
            }))
            .toPromise()
    }

    public async signup(username: string, email: string, password: string): Promise<boolean> {
        return this.http.post<LoginResponse>(await this.configurationService.getDjangoUrl(urls.signup), {username, email, password})
            .pipe(this.handleResponse({
                200: r => {
                    this._user$.next(r.data.user);
                    this._token$.next(r.meta);
                    this.notificationService.add('Account created successfully. You have been logged in.', 'success');
                    return true;
                },
                401: status => {
                    // Need to validate email.
                    this.notificationService.add('Account created successfully. Check your email for further instructions.', 'success');
                    return true;
                },
                403: 'Signup disabled',
                409: 'Email or username already in use',

                default: (e: ErrorResponse) => e.errors?.map(e => e.message).join(', ') ?? 'Unknown error'
            }))
            .toPromise()
    }

    public async verify_email(key: string): Promise<boolean> {
        return this.http.post<LoginResponse>(await this.configurationService.getDjangoUrl(urls.verify_email), {key})
        .pipe(this.handleResponse({
            200: r => {
                this._token$.next(r.meta);
                this._user$.next(r.data.user);
                this.notificationService.add('Email verified successfully. You have been logged in.', 'success');
                return true;
            },
            default: (e: ErrorResponse) => e.errors?.map(e => e.message).join(', ') ?? 'Unknown error'
        }))
        .toPromise();
    }

    public async password_reset_request(email: string): Promise<boolean> {
        return this.http.post<BaseResponse>(await this.configurationService.getDjangoUrl(urls.password_reset_request), {email})
            .pipe(this.handleResponse({
                200: r => {
                    this.notificationService.add('Password reset email sent. Check your email for instructions.', 'success');
                    return true;
                },
                default: (e: ErrorResponse) => e.errors?.map(e => e.message).join(', ') ?? 'Unknown error'
            }))
            .toPromise();
    }

    public async password_reset(key: string, newPassword: string): Promise<boolean> {
        return this.http.post<LoginResponse>(await this.configurationService.getDjangoUrl(urls.password_reset), {key, password: newPassword})
            .pipe(this.handleResponse({
                200: r => {
                    this._token$.next(r.meta);
                    this._user$.next(r.data.user);
                    this.notificationService.add('Password reset successfully. You have been logged in.', 'success');
                    return true;
                },
                401: (r: BaseResponse) => {
                    this.notificationService.add('Password reset successfully.', 'success');
                    return true;
                },
                default: (e: ErrorResponse) => e.errors?.map(e => e.message).join(', ') ?? 'Unknown error'
            }))
            .toPromise()
    }
}

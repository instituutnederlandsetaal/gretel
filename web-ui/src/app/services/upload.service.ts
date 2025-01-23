import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpEvent, HttpEventType, HttpRequest } from '@angular/common/http';
import { catchError, lastValueFrom, map, Observable, ReplaySubject, throwError } from 'rxjs';
import { ConfigurationService } from './configuration.service';

export class UploadStreamEvent {
    constructor(
        public message: string,
        public progress: number,
        public response: UploadResponse|undefined = undefined
    ) {}
}

export class UploadStreamError {
    constructor(public message: string) {}
}

export type UploadResponse = {
    upload_id: string;
}

export type UploadProgressResponse = {
    status: 'PENDING'|'PROGRESS'|'SUCCESS'|'FAILURE';
    info: {
        message: string;
        done: boolean;
        
        error?: string;
        total_files?: number;
        processed_files?: number;
        total_components?: number;
        processed_components?: number;
        words?: number;
        sentences?: number;
    }
}

@Injectable({
    providedIn: 'root'
})
export class UploadService {
    constructor(
        private http: HttpClient,
        private configurationService: ConfigurationService,
    ) { }

    private handleProgressForFile(file: File): (event: HttpEvent<UploadResponse>) => UploadStreamEvent {
        return (event: HttpEvent<UploadResponse>) => {
            switch (event.type) {
                case HttpEventType.Sent:
                    return new UploadStreamEvent(`Uploading file "${file.name}" of size ${file.size}.`, 0);
                case HttpEventType.UploadProgress:
                    const percentDone = event.total ? Math.round(100 * event.loaded / event.total) : 0;
                    return new UploadStreamEvent(`File "${file.name}" is ${percentDone}% uploaded.`, percentDone);
                case HttpEventType.Response:
                    return new UploadStreamEvent(`File "${file.name}" was completely uploaded!`, 100, event.body);
                default:
                    return new UploadStreamEvent('', -1);
            }
        }
    }

    /** Map the error into an UploadStreamError and send it out on the error channel. */
    private handleError(error: HttpErrorResponse): Observable<never> {
        if (error.status === 0) {
            // A client-side or network error occurred. Handle it accordingly.
            return throwError(() => new UploadStreamError('Failed to communicate with server; please try again later.'));
        } else {
            const r: UploadProgressResponse = error.error;
            // The backend returned an unsuccessful response code.
            // error.error contains the response body.
            // TODO should probably expose more info.
            const detail = r?.info?.error || r?.info?.message || error.error?.detail || error.message;
            return throwError(() => new UploadStreamError(`Failed to upload or parse file: ${detail}`));
        }
    }

    private async poll_upload(upload$: ReplaySubject<UploadStreamEvent>, upload_id: string) {
        const url = await this.configurationService.getDjangoUrl(`upload/status/${upload_id}/`)
        let retries = 0;
        let intervalMs = 1000;
        const start = new Date().getTime();
        do {
            try {
                retries++;
                intervalMs = 2500;
                const response = await lastValueFrom(this.http.get<UploadProgressResponse>(url, {withCredentials: true, responseType: 'json'}));
                if (response.status === 'PENDING') {
                    intervalMs = 10000;
                    const elapsedSeconds = Math.round((new Date().getTime() - start) / 1000);
                    upload$.next(new UploadStreamEvent(`Waiting for server to begin processing (${elapsedSeconds} seconds)...`, 0));
                } else if (response.status === 'PROGRESS') {
                    const progressPercentage = response.info.total_files > 0 ? Math.round(100 * response.info.processed_files / response.info.total_files) : 0;
                    const fileProgress = response.info.processed_files > 0 ? `${response.info.processed_files}/${response.info.total_files} files` : '';
                    const componentProgress = response.info.processed_components > 0 ? `${response.info.processed_components}/${response.info.total_components} components` : '';
                    const wordsAndSentences = response.info.words > 0 ? `${response.info.words} words, ${response.info.sentences} sentences` : '';
                    const message = `${response.info.message} - ${[fileProgress, componentProgress, wordsAndSentences].filter(x => x).join(', ')}`;
                    upload$.next(new UploadStreamEvent(message, progressPercentage));
                } else if (response.status === 'SUCCESS') {
                    upload$.next(new UploadStreamEvent('Upload complete!', 100));
                    upload$.complete();
                    break;
                } else if (response.status === 'FAILURE') {
                    upload$.error(new UploadStreamError(response.info.error));
                    break;
                }

                await new Promise(r => setTimeout(r, intervalMs)); // wait a little while before polling again.
            } catch {
                upload$.error(new UploadStreamError('Failed to poll upload status.'));
                break;
            }
        } while (true);
    }

    /**
     * Logs the user in, returns true if successful
     */
    upload(params: {
        treebankName: string,
        treebankDescription: string,
        treebankDisplay: string,
        treebankHelpUrl: string,
        file: File,
        format: string,
        isPublic?: boolean,
    }): Observable<UploadStreamEvent>  {
        const formData = new FormData();

        const id = params.treebankName.trim().replace(/[^a-zA-Z0-9_]/g, '_')
        // See upload/serializers.py for the expected fields.
        formData.set('name', id);
        formData.set('title', params.treebankName);
        formData.set('description', params.treebankDescription);
        formData.set('url_more_info', params.treebankHelpUrl);
        formData.set('input_file', params.file);
        formData.set('input_format', params.format);
        formData.set('public', params.isPublic ? 'true' : 'false');
        
        const upload$ = new ReplaySubject<UploadStreamEvent>();

        this.configurationService.getDjangoUrl(`upload/create/${id}/`)
        .then(url => new HttpRequest('POST', url, formData, {
            withCredentials: true,
            reportProgress: true
        }))
        .then(s => this.http.request(s)
            .pipe(
                map(this.handleProgressForFile(params.file)),
                catchError(this.handleError)
            )
            .subscribe({
                next: (v: UploadStreamEvent) => {
                    upload$.next(v)
                    if (v.response) this.poll_upload(upload$, v.response.upload_id)
                },
                error: (v: UploadStreamError) => upload$.error(v),
                complete: () => {/* swallow completion of initial upload. */}
            })
        )
        return upload$;
    }
}

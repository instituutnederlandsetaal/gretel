import { Component } from '@angular/core';
import { NotificationService } from '../../services/notification.service';
import { UploadService, UploadStreamError, UploadStreamEvent } from '../../services/upload.service';
import { UserService } from '../../services/user.service';

@Component({
    selector: 'grt-upload',
    templateUrl: './upload.component.html',
    styleUrls: ['./upload.component.scss'],
})
export class UploadComponent {
    treebankName = '';
    treebankDescription= '';
    treebankHelpUrl = '';
    format = '';
    isPublic = false;
        
    file: File = null;

    warning = '';
    isUploading = false;
    uploadProgress = 0;

    constructor(
        private notificationService: NotificationService,
        private uploadService: UploadService,
        private userService: UserService,
    ) {}

    get canUpload() {
        return !!this.userService.user$.value;
    }

    selectFile(event: Event) {
        this.file = (event.target as HTMLInputElement).files[0];
    }

    upload() {
        this.warning = '';
        if (!this.canUpload) {
            this.warning = 'Please sign in to upload a dataset.';
            return;
        }
        if (!this.file) this.warning = 'Please select a file to upload';
        this.uploadService.upload({
            treebankName: this.treebankName,
            file: this.file,
            format: this.format,
            isPublic: this.isPublic,
            treebankDescription: this.treebankDescription,
            treebankHelpUrl: this.treebankHelpUrl,
            treebankDisplay: this.treebankName,
        })
        .subscribe({
            next: (v: UploadStreamEvent) => {
                this.notificationService.add(v.message, 'success');
                this.uploadProgress = v.progress;
            },
            error: (v: UploadStreamError) => {
                this.notificationService.add(v.message, 'error');
                this.warning = v.message;
                this.uploadProgress = -1;
            },
            complete: () => {
                this.isUploading = false;
                this.uploadProgress = 100;
            }
        })
    }
}

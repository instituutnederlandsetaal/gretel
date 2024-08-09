import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
import { firstValueFrom, Observable } from 'rxjs';

@Injectable()
export class ConfigurationService {
    private config: Promise<Config>;

    constructor(private httpClient: HttpClient) {
        this.config = firstValueFrom(this.loadConfig());
    }

    async getDjangoUrl(path: string) {
        return (await this.config).django + path;
    }

    private loadConfig(): Observable<Config> {
        return this.httpClient.get<Config>(`assets/config/config.${environment.name}.json`);
    }
}

interface Config {
    django: string;
}

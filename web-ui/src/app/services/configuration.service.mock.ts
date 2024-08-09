import { ConfigurationService } from './configuration.service';

/**
 * These are all the public properties of the ConfigurationService
 */
type ConfigurationServiceInterface = {
    [K in keyof ConfigurationService]: ConfigurationService[K]
};

export class ConfigurationServiceMock implements ConfigurationServiceInterface {
    async getDjangoUrl(path: string) {
        return '/' + path;
    }
}

import { Injectable } from '@angular/core';
import {Link, links} from "../app-routing/links";


@Injectable()
export class LinkService {

  constructor() { }

  public getMainLinks(): Link[]{
    return links;
  }
}

/**
 * Contains all the information about the links
 */
interface Link {
    name: string;
    link: string;
    external?: boolean
}

const links: Link[] = [
    {
        name: 'Home',
        link: '/home',
    },
    {
        name: 'BlackLab Search',
        link: 'https://gcnd.ivdnt.org/',
        external: true,
    },
    {
        name: 'Example-based Search',
        link: '/example-based-search',
    },
    {
        name: 'XPath Search',
        link: '/xpath-search',
    },
    // {
    //     name: 'Multiword Expressions',
    //     link: '/mwe-search',
    // },
    // {
    //     name: 'Upload',
    //     link: '/upload-treebank',
    // },
    {
        name: 'About',
        link: '/about',
    },
    {
        name: 'Documentation',
        link: '/documentation',
    },
];


export { Link, links };

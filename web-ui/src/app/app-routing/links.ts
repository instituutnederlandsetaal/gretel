/**
 * Contains all the information about the links
 */
interface Link {
    name: string;
    link: string;
    proxy: boolean;
}

const links: Link[] = [
    {
        name: 'Home',
        link: '/home',
        proxy: false,
    },
    {
        name: 'Example-based Search',
        link: '/example-based-search',
        proxy: true,
    },
    {
        name: 'XPath Search',
        link: '/xpath-search',
        proxy: false,
    },
    {
        name: 'Multiword Expressions',
        link: '/mwe-search',
        proxy: false,
    },
    {
        name: 'About',
        link: '/about',
        proxy: false,
    },
    {
        name: 'Documentation',
        link: '/documentation',
        proxy: false,
    },
];


export { Link, links };

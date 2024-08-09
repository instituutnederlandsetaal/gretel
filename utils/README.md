# `lassy_to_basex.py`

This script adds LASSY treebanks to BaseX for GrETEL 4 or manual use. For
GrETEL 5, use Django's `upload-lassy` management command so the treebanks are
registered with the backend. This script also creates the following files:

- `{TREEBANK}.php`: GrETEL configuration file
- The directory `treebank-parts`: GrETEL configuration files if components
  exist of multiple databases (this happens if the user wants to group multiple
  input files into one component using the ``--group-by`` option)
- `{TREEBANK}_components.csv`: a user-readable CSV file with information about
  all generated BaseX databases

The script creates separate databases for the components without duplicating
the complete corpus in a merged database. Input files are already in Alpino
XML format, and the script combines them using string manipulation.

## Usage

Run this script by providing the directory of the treebank input files as its
argument. The input directory should have a ``COMPACT`` folder with ``.dz``
files (compressed combinations of LASSY XML files). The ``.dz`` files may
be located in subdirectories.

By default, the script creates one component for each ``.dz`` file. However,
large treebanks may consist of hundreds of components and selecting these
individually generally makes no sense. Use the option ``--group-by`` to group
multiple files into one component. This option takes one argument and can be
either:

* A number, where all files having in common the first *n* characters in the
filename are grouped into one component. For example, the files
``wik00_part0001.data.dz`` and ``wik00_part0002.data.dz`` will be grouped
into a component with the name ``wik00`` if ``--group-by=5`` is given, but
``wik01_part0001.data.dz`` will go into component ``wik01``.
* A character and a number next to each other, where all files having in
common the beginning up to the *n*th occurance of the given character are
grouped into one component. For example, if ``-group-by=_3`` is given,
the files ``vetdocs_PDFs_EPAR_zubrin_022101nl1.data.dz`` and
``vetdocs_PDFs_EPAR_zubrin_022101nl2.data.dz`` will be grouped into the same
component named ``vetdocs_PDFs_EPAR``, because up to the third occurance of
the underscore the filenames are the same.

Use ``--help`` to get information about other options.

You can cancel the process at any time by pressing Ctrl+C. All files that have
already been imported will be ready to use. However, the next time the script
runs it will restart from the beginning.

## Requirements

In addition to the Python 3 standard library, this script requires the following
to Python package, which can be installed using pip:

- `BaseXClient`

The script needs a running BaseX server. After installing BaseX, start it using
the command `basexserver -S`.

The script reads its BaseX connection settings from
``lassy_to_basex_settings.py``. This file is optional and the default BaseX
settings are used if the file does not exist.

Make sure you have enough disk space: the BaseX databases are much larger than
the input files. For instance, the EUROPARL treebank is 2.1 GiB in size, but
its BaseX database takes 15.6 GiB of disk space. The script continually uses
around 2-3 GiB of system memory, although this may vary according to the BaseX
version.

The script has only been tested on Linux, but should work on Windows as well.

# rmc

Command line tool for converting to/from remarkable `.rm` version 6 (software
version 3) files.

## Installation

If you want nice font rendering, you will need to install chrome/chromium (used
to create svg/pdf with embedded fonts). Otherwise, rendering will fall back to
using cairo. Chrome based rendering can also be turned off with `--no-chrome`.

To install in your current Python environment:

    pip install rmc
    
Or use [pipx](https://pypa.github.io/pipx/) to install in an isolated
environment (recommended):

    pipx install rmc

To use reMarkable's custom fonts (optional, for more accurate text rendering):

    ./download_remarkable_fonts.sh

Then run rmc with the option `--fonts-dir fonts/` to use these fonts.

This downloads the following files into `fonts/`:
- `reMarkableSans.woff2`
- `reMarkableSerif.woff2`
- `reMarkableSerifItalic.woff2`

Without these fonts, rmc uses bundled open-source alternatives (Noto Sans, EB Garamond).

## Usage

Convert rm to pdf:

    $ rmc file.rm -o file.pdf

Convert rm to svg:

    $ rmc file.rm -o file.svg

Convert a remarkable v6 file to other formats, specified by `-t FORMAT`:

    $ rmc -t markdown file.rm -o file.md 

Create a `.rm` file containing the text in `text.md`:

    $ rmc -t rm text.md -o text.rm

```
$ rmc --help
Usage: rmc [OPTIONS] [INPUT]...

  Convert to/from reMarkable v6 files.

  Available FORMATs are: `rm` (reMarkable file), `markdown`, `svg`, `pdf`,
  `blocks`, `blocks-data`.

  Formats `blocks` and `blocks-data` dump the internal structure of the `rm`
  file, with and without detailed data values respectively.

Options:
  --version            Show the version and exit.
  -v, --verbose
  -f, --from FORMAT    Format to convert from (default: guess from filename)
  -t, --to FORMAT      Format to convert to (default: guess from filename)
  -o, --output PATH    Output filename (default: write to standard out)
  --no-chrome          Use Cairo instead of Chrome for PDF conversion
  --chrome-loc PATH    Path to Chrome/Chromium binary
  --fonts-dir PATH     Directory containing reMarkable font files
  --device [RM2|RMPP]  Device type (overrides auto-detection)
  --help               Show this message and exit.
```

# Acknowledgements

`rmc` uses [rmscene](https://github.com/ricklupton/rmscene) to read the `.rm` files, for which https://github.com/ddvk/reader helped a lot in figuring out the structure and meaning of the files.

[@chemag](https://github.com/chemag) added initial support for converting to svg and pdf.

[@Seb-sti1](https://github.com/Seb-sti1) made lots of improvements to svg export and updating to newer `rmscene` versions.

[@ChenghaoMou](https://github.com/ChenghaoMou) added support for new pen types/colours.

[@EelcovanVeldhuizen](https://github.com/EelcovanVeldhuizen) for code updates/fixes.

[@p4xel](https://github.com/p4xel) for code fixes.

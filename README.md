# appleLoops.py

## Requirements
- python shipped with macOS (typically `python 2.7.10`)
- Active connection that can access `https://raw.githubusercontent.com` and `http://audiocontentdownload.apple.com`

## Capabilities
- Download loops from Apple's servers
- - Store downloaded loops in a mirrored path, useful for installing loops with this tool from a local http server.
- - Can specify a caching server to download loops through
- Build a DMG out of the downloaded loops (only at end of download run)
- Install loops for any of these apps installed on a macOS system:
- - GarageBand (10.1.1 or newer)
- - Logic Pro X (10.2.1 or newer)
- - MainStage 3 (3.2.3 or newer)

## Installing loops
Every so often, Apple likes to change the loops that a particular audio app requires to run. Keeping up with this using munki or Casper Pro/JSS can be a pain in the neck. To make this easier, `appleLoops.py` now has the ability to install loops using `--deployment` mode.

When `appleLoops.py --deployment --mandatory-only` (or just/including `-o/--optional-only`) is run, it checks the `/Applications` folder to determine if GarageBand, Logic Pro X, or MainStage 3 are installed. If any of these apps are installed, it will then  determine what loops are already installed, what loops aren't installed, and what loops need upgrading.

Following this, loops are downloaded, installed, removed from `/tmp` until all specified loops have been installed.

## Deployment
### Simple deployment process
1. The app that loops are being installed for _must_ be installed before using `appleLoops.py` to deploy the loop packages.
1. `appleLoops.py` must be on the computer somewhere, i.e. `/usr/local/bin`. Must make the script executable and readable by `root`.
1. _For current testing purposes, do a dry run before actual run:_ `/usr/local/bin/appleLoops.py --dry-run --deployment -m -o`.
1. Using the appropriate mechanism for your deployment tool, run: `/usr/local/bin/appleLoops.py --deployment -m -o`. This needs to be run as `root`, you will be prompted to use `sudo` if necessary.

### Advanced deployment process
1. Download loops for _all_ apps you deploy, for example: ```./appleLoops.py --apps garageband mainstage --mirror-paths --destination /Volumes/Data/apple_audio_content --mandatory-only --optional-only```
1. Get the folders `lp10_ms3_content_YYYY` (where `YYYY` represents a year) onto a web server your managed Macs have access to.
1. Steps 1-3 as per _Simple deployment process_.
1. _For current testing purposes, do a dry run before actual run: `/usr/local/bin/appleLoops.py --dry-run --deployment -m -o --pkg-server http://example.org/apple_loops`.
1. Using the appropriate mechanism for your deployment tool, run: `/usr/local/bin/appleLoops.py --deployment -m -o --pkg-server http://example.org/apple_loops`. This needs to be run as `root`, you will be prompted to use `sudo` if necessary.

More information about deployment can be found in the [Wiki](../../wiki).

**Important note:**

`appleLoops.py` expects to be able to find folders named `lp10_ms3_content_YYYY` wherever you've supplied the `--pkg-server` option, if it can't find packages in this location, it will fallback to using the Apple servers.

For machines managed with munki, `appleLoops.py` will attempt to find the munki `SoftwareRepoURL` in the configuration for that machine, for example `http://example.org/munki_repo` - make sure the folders `lp10_ms3_content_YYYY are in `munki_repo` (or appropraite folder as per your configuration).`

Local mirror deployments have some caveats as outlined here - https://github.com/carlashley/appleLoops/wiki/Local-Mirror-Deployment

Caching Server deployents also have some caveats as outlined here - https://github.com/carlashley/appleLoops/wiki/Caching-Server-Deployment

## Other usage
For a full set of arguments/usage options, `./appleLoops.py --help`


## Bug reports
If you happen to run into issues, please raise an [issue](../../issues) with the following info:
- The command used
- Re-run the same command with the `--debug --log-path ~/Desktop` (or other suitable log path location)
- - Include the log for the debug run in the issue
- Version: `appleLoops.py --version`

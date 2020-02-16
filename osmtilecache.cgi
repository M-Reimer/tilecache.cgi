#!/usr/bin/perl
#    osmtilecache.cgi - OSM Map tile cache proxy with asynchronous tile update
#    Copyright (C) 2020 Manuel Reimer <manuel.reimer@gmx.de>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

use strict; # Add these as early as possible
use warnings;

#
# Config area
#

# Set your borders here. You should limit the size of your cache to the region
# that is really interesting/important in your map project.
# Tool to calculate the disk usage: http://tools.geofabrik.de/calc/
my $ZOOM_MIN = 12;
my $ZOOM_MAX = 17;
my $BORDER_LEFT = 9.23;
my $BORDER_BOTTOM = 49.76;
my $BORDER_RIGHT = 10.01;
my $BORDER_TOP = 50.22;

# How long are tiles valid in your cache before we try to update them?
my $MAX_CACHE_TIME_DAYS = 2;

# The server we mirror from.
my $TILE_SERVER = 'https://a.tile.openstreetmap.org';

# Paths. You should not have to edit them in most cases.
my $CACHEDIR = dirname(__FILE__) . '/cache';
my $UPDATELISTPATH = "$CACHEDIR/update.lst";


#
# From this point on there should be no reason to do any changes in regular use
#

# All the includes we need
use CGI::Carp qw/fatalsToBrowser/;
use Math::Trig;
use File::Basename;
use File::Path qw(make_path);
use File::stat;
use LWP::UserAgent;
use POSIX qw(strftime);
use Fcntl qw/:DEFAULT :flock/;
use Compress::Zlib;

{ #main
  # PATH_INFO contains the tile path and has to be defined!
  StatusDenied() if (!defined($ENV{PATH_INFO}));

  # Trigger update if PATH_INFO is '/update'
  if ($ENV{PATH_INFO} eq '/update') {
    DoUpdate();
    print "Content-type: text/plain\n\n";
    print "DONE\n";
    exit(0);
  }

  # Validate $tile_path, split parts
  StatusDenied() if ($ENV{PATH_INFO} !~ m#^/([0-9]+)-([0-9]+)-([0-9]+)\.png$#);
  my $zoom = $1;
  my $tilex = $2;
  my $tiley = $3;
  my $tile_path = "$zoom/$tilex/$tiley.png";

  # Apply set borders. Send Status 404 for tiles out of our defined range
  StatusOutOfRange() if ($zoom > $ZOOM_MAX || $zoom < $ZOOM_MIN);
  my ($minx, $miny) = getTileNumber($BORDER_TOP, $BORDER_LEFT, $zoom);
  my ($maxx, $maxy) = getTileNumber($BORDER_BOTTOM, $BORDER_RIGHT, $zoom);
  StatusOutOfRange() if ($tilex > $maxx || $tilex < $minx);
  StatusOutOfRange() if ($tiley > $maxy || $tiley < $miny);

  #
  # At this point we know that $tile_path is a valid tile path
  #

  # Get local path to cache file and remote URL
  my $localpath = "$CACHEDIR/$tile_path";
  my $url = "$TILE_SERVER/$tile_path";

  # If no cache tile exists, then we have to get this tile synchronously.
  if (!-s $localpath) {
    GetOneTile($url, $localpath);
  }

  # If we fail to get a tile, then end with error
  StatusNotFound() if (!-s $localpath);

  # If the tile is just outdated, remember the tile path for later update
  if (-M $localpath > $MAX_CACHE_TIME_DAYS) {
    AppendLineToFile($tile_path, $UPDATELISTPATH);
  }

  # Deliver cache file to browser
  my $dateformat = '%a, %d %b %Y %H:%M:%S GMT';
  my $mtime = stat($localpath)->mtime;
  my $lastmod = strftime($dateformat, gmtime($mtime));
  my $expires = strftime($dateformat, gmtime($mtime + 24 * 60 * 60 * $MAX_CACHE_TIME_DAYS));
  print "Expires: $expires\n";
  print "Last-Modified: $lastmod\n";
  print "Content-type: image/png\n\n";
  open(my $fh, '<', $localpath);
  flock($fh, LOCK_SH) or die($!);
  print while <$fh>;
  flock($fh, LOCK_UN);
  close($fh);
}

sub getTileNumber {
  my ($lat,$lon,$zoom) = @_;
  my $xtile = int( ($lon+180)/360 * 2**$zoom ) ;
  my $ytile = int( (1 - log(tan(deg2rad($lat)) + sec(deg2rad($lat)))/pi)/2 * 2**$zoom ) ;
  return ($xtile, $ytile);
}

# Reads update list and downloads the files
sub DoUpdate {
  sysopen(my $listfh, $UPDATELISTPATH, O_RDWR | O_CREAT) or die($!);
  flock($listfh, LOCK_EX);
  my @paths = <$listfh>;
  chomp(@paths);
  truncate($listfh, 0);
  flock($listfh, LOCK_UN);
  close($listfh);

  my $counter = 0;
  foreach my $path (@paths) {
    my $localpath = "$CACHEDIR/$path";
    my $url = "$TILE_SERVER/$path";
    GetOneTile($url, $localpath) or die("Failed to download $url");
    # Maximum of 100 tiles per run. Drop the others.
    last if ($counter++ > 100);
  }
}

# Appends a line to a file if the line is not already in there
sub AppendLineToFile {
  my ($aLine, $aPath) = @_;
  sysopen(my $listfh, $aPath, O_RDWR | O_CREAT) or die($!);
  flock($listfh, LOCK_EX);
  my $found = 0;
  while (my $line = <$listfh>) {
    chomp($line);
    if ($line eq $aLine) {
      $found = 1;
      last;
    }
  }
  print $listfh "$aLine\n" if (!$found);
  flock($listfh, LOCK_UN);
  close($listfh);
}

# PNG validator. Validates header and CRC32 checksums.
sub ValidatePNG {
  my ($aData) = @_;
  open(my $fh, '<', \$aData) or return 0;

  # Validate header first
  read($fh, my $header, 8);
  return 0 if ($header ne "\x89PNG\x0d\x0a\x1a\x0a");

  # CRC check every chunk
  while(read($fh, my $blength, 4)) {
    my ($length) = unpack('L>', $blength);
    return 0 if (read($fh, my $chunktype, 4) != 4);
    return 0 if (read($fh, my $chunkdata, $length) != $length);
    return 0 if (read($fh, my $bsavedcrc, 4) != 4);
    my $savedcrc = unpack('L>', $bsavedcrc);
    return 0 if ($savedcrc != crc32("$chunktype$chunkdata"));
  }

  return 1;
}

# Fetches one tile from $aURL to $aCachePath
# File locking is used to prevent multiple downloads of the same file and
# race conditions while writing the actual image file
sub GetOneTile {
  my ($aURL, $aCachePath) = @_;
  my $lockfile = "$aCachePath.lck";

  # Get sure the path to the image file exists
  make_path(dirname($aCachePath));

  # Lock a lock file next to the image file before attempting to download
  # If this fails, we expect someone else already handling this file.
  open (my $lockfh, '>', $lockfile) or die($!);
  return unless flock($lockfh, LOCK_EX | LOCK_NB);

  # Download/update the image file
  my $success = 0;
  my $ua = LWP::UserAgent->new;
  $ua->agent("Tile Cache on $ENV{SERVER_NAME}");
  $ua->default_header('Referer' => "https://$ENV{SERVER_NAME}/");
  $ua->timeout(30); # Reduce the timeout to 30 seconds
  my $response = $ua->get($aURL);
  if ($response->is_success && ValidatePNG($response->content)) {
    $success = 1;
    my $content = $response->content;
    sysopen(my $fh, $aCachePath, O_WRONLY | O_CREAT) or die($!);
    flock($fh, LOCK_EX) or die("Failed to lock image file!");
    truncate($fh, 0);
    print $fh $content;
    flock($fh, LOCK_UN);
    close($fh);
  }

  # Get rid of the lock file
  flock($lockfh, LOCK_UN);
  unlink($lockfile);
  return $success;
}

sub StatusDenied {
  print "Status: 403\n";
  print "Content-type: text/html\n\n";

  print <<EOF;
<!DOCTYPE html>
<html><head>
<title>403 Forbidden</title>
</head><body>
<h1>Forbidden</h1>
<p>You don't have permission to access $ENV{SCRIPT_NAME}
on this server.<br />
</p>
</body></html>
EOF

  exit(0);
}

# DANGER: XSS risk if used before PATH_INFO has been validated!
sub StatusNotFound {
  print "Status: 404\n";
  print "Content-type: text/html\n\n";

  print <<EOF;
<!DOCTYPE html>
<html><head>
<title>404 Not Found</title>
</head><body>
<h1>404 Not Found</h1>
<p>The requested URL $ENV{SCRIPT_NAME}/$ENV{PATH_INFO} was not found
on this server.<br />
</p>
</body></html>
EOF

  exit(0);
}

# DANGER: XSS risk if used before PATH_INFO has been validated!
sub StatusOutOfRange {
  print "Status: 404\n";
  print "Content-type: text/html\n\n";

  print <<EOF;
<!DOCTYPE html>
<html><head>
<title>404 Not Found</title>
</head><body>
<h1>404 Not Found</h1>
<p>The requested URL $ENV{SCRIPT_NAME}/$ENV{PATH_INFO} is out of range for this cache server.<br />
</p>
</body></html>
EOF

  exit(0);
}

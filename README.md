osmtilecache.cgi
================

Introduction
------------

In this repository you'll find a tile caching proxy with the following features:

- Easy setup. Just drop the CGI file on your web server, change the config in the CGI file for your needs and configure your map tool (for example Leaflet) to use it
- Region limit to reduce disk usage on your server and make it less attractive for abuse by others
- Asynchronous map tile update

To access the tiles, the URL will be as follows:

    osmtilecache.cgi/$zoom-$tilex-$tiley.png

You have to set up a "cron mechanism" which loads the following URL from time to time to get the update done:

    osmtilecache.cgi/update

You should load this regularly so the list of files fetched from the official tile server does not get too long to be considered to be mass downloading.

So far tile updating can not be triggered from console but only via HTTP from your web server as that's what my hoster offers for cron jobs. Making it possible to call the CGI directly with some parameter to trigger the update would be an easy fix, so if you need this, please create an Issue.

LICENSE
-------

This project uses the GNU Affero GPL in version 3.0 or above.

This means: If you use this project on your own server and improve the script, then you **have to** share your changes.

The easiest way would be if you just provide your changes as Pull Request to this repository. In this case you can just point anyone, who wants your modifications, to the original project.

Configuration changes are not considered to be such changes, so please don't create Pull Requests with your configuration ;)

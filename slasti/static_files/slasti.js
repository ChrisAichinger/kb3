slasti_js_dir = (function () {
    // Save slasti.js dir for later: stackoverflow.com/questions/8523200
    var scriptEls = document.getElementsByTagName('script');
    var scriptPath = scriptEls[scriptEls.length - 1].src;
    var scriptFolder = scriptPath.substr(0, scriptPath.lastIndexOf( '/' )+1 );
    return scriptFolder;
})()

$(document).ready(function() {
    var favIcon = "\
    iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAAAM1BMVEWAF46iDrilHbawPcO1\
    ScO5VcrAZc/CbtHIeNPNh9raqePitOTqzO/x3fT26Pb+8/r9//z/O9A1AAAAAXRSTlMAQObY\
    ZgAAAAFiS0dEAIgFHUgAAABnSURBVBjTfc/BDsQgCARQB7Zoq9T5/6+tbtZN6aGc4AUSJiWE\
    So95CJBb715A0r9QeJgVG/0PvK7tBU0iZLrJHbA1nuUOgFbWAMBOjWD8LJB9U83u/xM5x4v9\
    0PnpqHkiKhKyvMdNF1yNBFxyrc1oAAAAAElFTkSuQmCC";

    var docHead = document.getElementsByTagName('head')[0];
    var newLink = document.createElement('link');
    newLink.rel = 'shortcut icon';
    newLink.href = 'data:image/png;base64,' + favIcon;
    docHead.appendChild(newLink);


    $(".note").each(function(index, elem) {
        var converter = new Showdown.converter();
        var html = converter.makeHtml($(this).html());
        $(this).html(html);
    });


    function process_loc_data(data) {
        // Transform data into a jQuery object
        var jq_data = $('<div/>').html(data);

        // Iterate over bookmarks to find loc: directives and mark names
        var bookmarks = [];
        jq_data.find('.bookmark').each(function (i, elem) {
            // Redeclare regex within loop. Otherwise we hit a FF bug:
            // http://stackoverflow.com/questions/10167323
            var loc_regex = /loc:([+-]?[.0-9]+),([+-]?[.0-9]+)([^<\n]*)/g;
            while ((m = loc_regex.exec(elem.innerHTML)) != null)
            {
                var lat = parseFloat(m[1]);
                var lon = parseFloat(m[2]);
                var comment = m[3].trim();
                var separator = comment.length ? " - " : "";
                var mark_text = $(elem).find('.mark').text();
                var mark_href = $(elem).find('.mark').attr("href");
                var name = $(elem).find('.mark_link').text();
                var href = $(elem).find('.mark_link').attr("href");
                var tags = $(elem).find('.mark_tag').map(function(i, el) {
                    return $(el).text().toLowerCase();
                }).get();
                bookmarks.push({lat: lat, lon: lon,
                                mark_text: mark_text, mark_href: mark_href,
                                name: name, comment: comment, href: href,
                                description: name + separator + comment,
                                tags: tags});
            }
        });

        // Ask the user which tags she wants to map.
        // Pressing "Ok" will cause the map and bookmarks to be displayed.
        $("#map_search").css({display: "block"});
        $("#map_search").data("bookmarks", bookmarks);
    }

    $("#map_search_cancel").click(function(evt) {
        $("#map_search").css({display: "none"});
    });
    $("#map_search_ok").click(function(evt) {
        $("#map_search").css({display: "none"});
        var queries = $("#map_search_query").val().trim();
        var bookmarks = $("#map_search").data("bookmarks");
        if (!queries) {
            // No query string given, show all marks with "loc:" data.
            map_plot({'all': bookmarks});
            return;
        }
        queries = queries.split(/\s+/);
        var plot_items = new Object();
        $.each(queries, function (index, query) {
            var invert = false;
            if (query[0] == '^' || query[0] == '!') {
                query = query.substr(1);
                invert = true;
            }
            var lower_query = query.toLowerCase()
            var matching_marks = $.grep(bookmarks, function(mark, i) {
                return $.inArray(lower_query, mark.tags) != -1;
            }, invert);
            plot_items[query] = matching_marks;
        });

        // Show the map and the selected bookmarks.
        map_plot(plot_items);
    });

    $("#mapclosebtn").click(function(evt) {
        map.destroy();
        $("#mapwrap").css({display: "none"});
    });

    function map_plot(plot_items) {
        $("#mapwrap").css({display: "block"});

        var mapbox = new OpenLayers.Layer.XYZ("MapBox Streets", [
            "https://a.tiles.mapbox.com/v3/greek0.h0a1ljej/${z}/${x}/${y}.png",
            "https://b.tiles.mapbox.com/v3/greek0.h0a1ljej/${z}/${x}/${y}.png",
            "https://c.tiles.mapbox.com/v3/greek0.h0a1ljej/${z}/${x}/${y}.png",
            "https://d.tiles.mapbox.com/v3/greek0.h0a1ljej/${z}/${x}/${y}.png",
            ], {
                attribution:
                    "Tiles &copy; <a href='http://mapbox.com/'>MapBox</a> | " +
                    "Data &copy; <a href='http://www.openstreetmap.org/'>" +
                    "OpenStreetMap</a> and contributors, CC-BY-SA",
                sphericalMercator: true,
                wrapDateLine: true,
                //transitionEffect: "resize",
                // buffer: 1,
                numZoomLevels: 17,
                //'maxExtent': new OpenLayers.Bounds(1000,100,-1000,-100)
            },
            {isBaseLayer: true});

        // Bootstrap OpenLayers
        map = new OpenLayers.Map("mapdisplay");
        map.addLayer(mapbox);
        /*map.addLayer(new OpenLayers.Layer.Bing({
                            name: "Road",
                            key: "AqTGBsziZHIJYYxgivLBf0hVdrAk9mWO" +
                                 "5cQcb8Yux8sW5M8c8opEC2lZqKR1ZZXf",
                            type: "Road"
                        }));*/

        var epsg4326 = new OpenLayers.Projection("EPSG:4326"); // WGS 84
        var projectTo = map.getProjectionObject();     // Map projection

        var all_coords = [];
        $.each(plot_items, function(name, coords) {
            // Append coords array to all_coords.
            Array.prototype.push.apply(all_coords, coords);
        });
        // Calculate the map center
        var sumLon = all_coords.reduce(function(f, c) { return f+c.lon; }, 0);
        var sumLat = all_coords.reduce(function(f, c) { return f+c.lat; }, 0);
        var centerLon = sumLon / all_coords.length;
        var centerLat = sumLat / all_coords.length;
        var lonLat = new OpenLayers.LonLat(centerLon, centerLat)
                                   .transform(epsg4326, projectTo);
        var zoom=5;
        map.setCenter(lonLat, zoom);

        var colors = ["#e00", "#0f0", "#33f", "#ee0", "#c0c", "#0cc",
                      "#f80", "#0fa", "#0af", "#192", "#912", "#12a"];
        var color_index = 0;
        // Define markers as "features" of the vector layer:
        var vectorLayer = new OpenLayers.Layer.Vector("Overlay");
        $.each(plot_items, function(name, coords) {
            var color = colors[color_index % colors.length];
            color_index++;
            $.each(coords, function(i, coord) {
                var feature = new OpenLayers.Feature.Vector(
                        new OpenLayers.Geometry.Point(coord.lon, coord.lat)
                                               .transform(epsg4326, projectTo),
                        coord,
                        {title: coord.description,
                         fillColor: color, strokeColor: "#000",
                         strokeWidth: 1,
                         strokeLinecap: "round",
                         strokeDashstyle: "solid",
                         pointRadius: 5,
                         pointerEvents: "visiblePainted",
                         labelAlign: "cm",
                         labelOutlineColor: "white",
                         labelOutlineWidth: 3,
                    });
                vectorLayer.addFeatures(feature);
            });
        });
        map.addLayer(vectorLayer);

        // Add a selector control to the vectorLayer with popup functions
        var controls = {
          selector: new OpenLayers.Control.SelectFeature(vectorLayer,
                           { onSelect: createPopup, onUnselect: destroyPopup })
        };

        function createPopup(feature) {
          var coord = feature.attributes;
          feature.popup = new OpenLayers.Popup.FramedCloud("pop",
              feature.geometry.getBounds().getCenterLonLat(),
              null,
              '<div class="markerContent">' +
                  '[<a href="' + coord.mark_href + '">' +
                                 coord.mark_text + '</a>] ' +
                  '<a href="' + coord.href + '">' + coord.name + '</a>' +
                  (coord.comment.length ? ('<br/>' + coord.comment) : "") +
                  '</div>',
              null,
              false,
              function() { controls['selector'].unselectAll(); }
          );
          feature.popup.closeOnMove = true;
          feature.popup.autosize = true;
          map.addPopup(feature.popup);
        }

        function destroyPopup(feature) {
          feature.popup.destroy();
          feature.popup = null;
        }

        map.addControl(controls['selector']);
        controls['selector'].activate();
    }


    $("#loc_parse").click(function(evt) {
        // First load openlayers slippymap
        var openlayers = slasti_js_dir + "OpenLayers/OpenLayers.light.js";
        $.getScript(openlayers, function(data, textStatus, jqxhr) {
            // _getScriptLocation doesn't work when loaded via jQuery, fix it
            OpenLayers._getScriptLocation = function() {
                return slasti_js_dir + "OpenLayers/";
            };

            // Then load all loc: containing entries and process them
            var search_url = $("form[action *= 'search']").attr('action');
            $.get(search_url + "?q=loc:&nopage=1", process_loc_data);
        });
    });

    $("#markdown_cheatsheet_btn").click(function(evt) {
        $("#markdown_cheatsheet").css({display: "block"});
    });

});
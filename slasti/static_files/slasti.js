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
        var results = [];
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
                var name = $(elem).find('.mark_link').text();
                var href = $(elem).find('.mark_link').attr("href");
                results.push({lat: lat, lon: lon,
                              name: name, comment: comment, href: href,
                              description: name + separator + comment});
            }
        });

        // Display the map and show the points on it
        map_plot(results);
    }

    $("#mapclosebtn").click(function(evt) {
        map.destroy();
        $("#mapwrap").css({display: "none"});
    });

    function map_plot(coords) {
        $("#mapwrap").css({display: "block"});

        // Bootstrap OpenLayers
        map = new OpenLayers.Map("mapdisplay");
        map.addLayer(new OpenLayers.Layer.Bing({
                            name: "Road",
                            key: "AqTGBsziZHIJYYxgivLBf0hVdrAk9mWO5cQcb8Yux8sW5M8c8opEC2lZqKR1ZZXf",
                            type: "Road"
                        }));

        var epsg4326 = new OpenLayers.Projection("EPSG:4326"); // WGS 84
        var projectTo = map.getProjectionObject();     // Map projection

        // Calculate the map center
        var sumLon = coords.reduce(function (f, c) { return f + c.lon; }, 0);
        var sumLat = coords.reduce(function (f, c) { return f + c.lat; }, 0);
        var centerLon = sumLon / coords.length;
        var centerLat = sumLat / coords.length;
        var lonLat = new OpenLayers.LonLat(centerLon, centerLat)
                                   .transform(epsg4326, projectTo);
        var zoom=5;
        map.setCenter(lonLat, zoom);

        // Define markers as "features" of the vector layer:
        var marker = OpenLayers.Util.getImagesLocation() + "marker.png";
        var vectorLayer = new OpenLayers.Layer.Vector("Overlay");
        $.each(coords, function(i, coord) {
            var feature = new OpenLayers.Feature.Vector(
                    new OpenLayers.Geometry.Point(coord.lon, coord.lat)
                                           .transform(epsg4326, projectTo),
                    coord,
                    {title: coord.description,
                     fillColor: "#e00", strokeColor: "#000",
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

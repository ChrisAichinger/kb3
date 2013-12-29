
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

    $("#loc_parse").click(function(evt) {
        // Load all loc: containing entries, then process them
        var search_url = $("form[action *= 'search']").attr('action');
        $.get(search_url + "?q=loc:&nopage=1", function(data) {
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
                    var lat = m[1];
                    var lon = m[2];
                    var comment = m[3].trim();
                    comment = comment.length ? (" - " + comment) : "";
                    var name = $(elem).find('.mark_link').text();
                    results.push([lat.toString(), lon.toString(), "circle5",
                                  "red", "", name + comment].join('\t'));
                }
            });

            // Send the results to copypastemap.com
            // See harrywood.co.uk/maps/examples/openlayers/marker-popups.html
            // for a more robust solution.
            results = results.join('\n');
            var res = $('<form method="post" ' +
              'action="http://copypastemap.com/map.php" style="display:none">' +
              '<textarea name="xldata" id="xldata" style="width:100%">' +
              results + '</textarea>' +
              '<input name="Submit" id="Submit" value="MAP!" type="text" />' +
              '</form>');
            $("body").append(res);
            res.submit();
        });
    });

});

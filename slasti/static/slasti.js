slasti_js_dir = (function () {
    // Save slasti.js dir for later: stackoverflow.com/questions/8523200
    var scriptEls = document.getElementsByTagName('script');
    var scriptPath = scriptEls[scriptEls.length - 1].src;
    var scriptFolder = scriptPath.substr(0, scriptPath.lastIndexOf( '/' )+1 );
    return scriptFolder;
})()


class LocalStorageCache {
    constructor() {
        const markId = $("form[name='editform']").attr('data-mark-id')
        const keyId = markId ? 'mark-' + markId : 'new-' + $("input[name='url']").val();
        this.lastExpirationKey = 'slasti-last-expiration';
        this.notePrefix = 'slasti-note-';
        this.metaPrefix = 'slasti-meta-';
        this.noteKey = this.notePrefix + keyId;
        this.metaKey = this.metaPrefix + keyId;

        this.expireCheckMilliSec = 1000*3600*24*7;
        this.cacheLifetimeMilliSec = 1000*3600*24*30;
        if (this._isExpired(this.lastExpirationKey, this.expireCheckMilliSec)) {
            this.expireOldEntries();
            localStorage.setItem(this.lastExpirationKey, (+ new Date()).toString());
        }
    }
    get = () => {
        return localStorage.getItem(this.noteKey);
    }
    set = (val) => {
        localStorage.setItem(this.noteKey, val);
        localStorage.setItem(this.metaKey, (+ new Date()).toString());
    }
    remove = () => {
        localStorage.removeItem(this.noteKey);
        localStorage.removeItem(this.metaKey);
    }
    _isExpired = (key, timeoutMilliSec) => {
        const now = (+ new Date());
        const metaDate = parseInt(localStorage.getItem(key));
        return !metaDate || now - metaDate > timeoutMilliSec;
    }
    expireOldEntries = () => {
        for (let i=0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key.startsWith(this.metaPrefix) && this._isExpired(key, this.cacheLifetimeMilliSec)) {
                localStorage.removeItem(key);
                localStorage.removeItem(this.notePrefix + key.substr(this.metaPrefix.length));
            }
        }
    }
}


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

    var mkd_parser = new stmd.DocParser();
    var mkd_renderer = new stmd.HtmlRenderer();
    const localStorageCache = new LocalStorageCache();

    // Returns a function, that, as long as it continues to be invoked, will
    // not be triggered. The function will be called after it stops being
    // called for N milliseconds. If `immediate` is passed, trigger the
    // function on the leading edge, instead of the trailing.
    function debounce(func, wait, immediate) {
        var timeout;
        return function() {
            var context = this, args = arguments;
            var later = function() {
                timeout = null;
                if (!immediate) func.apply(context, args);
            };
            var callNow = immediate && !timeout;
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
            if (callNow) func.apply(context, args);
        };
    };
    const copyToClipboard = str => {
      const el = document.createElement('textarea');
      el.value = str;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    };
    function is_url_allowed(url) {
        if (/^https?:\/\//.test(url)
            || /^data:image\/png;/.test(url)
            || url.toString().startsWith(s_userurl)
        ) { return url }
    }
    function render_markdown_into(input, target) {
        const NOSANITIZE_TAG = '!no-sanitize\n';
        const skipSanitization = s_allow_unsanitized_html && input.startsWith(NOSANITIZE_TAG);
        if (input.startsWith(NOSANITIZE_TAG)) {
            input = input.substr(NOSANITIZE_TAG.length);
        }
        const mkd = mkd_parser.parse(input);
        const html = mkd_renderer.render(mkd);
        const sanitized = skipSanitization ? html : html_sanitize(html, is_url_allowed);
        target.html(sanitized);
    }
    const numNotes = $(".note").length;
    $(".note").each(function(index, elem) {
        if (!this.childNodes.length) {
            return;
        }
        const INPUT_CUTOFF_CHARACTERS = 1500;
        const full_input = this.childNodes[0].nodeValue;
        let input;
        if (numNotes > 1 && full_input.length > INPUT_CUTOFF_CHARACTERS) {
            input = full_input.substr(0, INPUT_CUTOFF_CHARACTERS) + '...';
        } else {
            input = full_input;
        }
        render_markdown_into(input, $(this));
        if (full_input !== input) {
            $("<p><a href='javascript:void' title='Expand'>[+]</a></p>")
                .click(() => render_markdown_into(full_input, $(this)))
                .appendTo($(this));
        }
    });

    const serverText = $("#note-text").text();
    const localText = localStorageCache.get();
    if (serverText.trim() === "" && localText) {
        $("#note-text").text(localText);
    }

    if (window.ace !== undefined) {
        ace.define("ace/theme/custom",["require","exports","module","ace/lib/dom"], function(require, exports, module) {
            exports.isDark = false;
            exports.cssClass = "ace-custom";
            exports.cssText = "";

            var dom = require("ace/lib/dom");
            dom.importCssString(exports.cssText, exports.cssClass);
        });

        window.editor = ace.edit("note-text");
        editor.setTheme("ace/theme/custom");
        editor.session.setMode("ace/mode/markdown");
        editor.session.setTabSize(2);
        editor.session.setUseSoftTabs(true);
        editor.session.setUseWrapMode(true)
        editor.renderer.setShowGutter(false);

        const parseAndRender = debounce(() => {
            $("#note-rendered-container").show();
            const input = editor.getValue();
            render_markdown_into(input, $("#note-rendered"));
            MathJax.Hub.Queue(["Typeset",MathJax.Hub,"note-rendered"]);
        }, 50);
        const saveLocalStorage = debounce(() => {
            if (editor.getValue()) {
                localStorageCache.set(editor.getValue());
            }
        }, 3000);
        const textarea = $("#note-textarea")
        editor.getSession().on('change', () => {
            textarea.val(editor.getValue());
            parseAndRender();
            saveLocalStorage();
        });
        const resizeObserver = new ResizeObserver(() => editor.resize())
        resizeObserver.observe($("#note-text").get()[0]);
        var expanded_notes = false;
        editor.on('focus', () => {
            if (expanded_notes) return;
            expanded_notes = true;
            $(".editform-container").animate(
                {"max-width": $(window).width() + "px"},
                500, 'swing',
                function() { $(this).css({"max-width": "100%"}); editor.resize(); })
        });
    }

    function registerTitleLineEventHandlers() {
        var canHideMetaLinks = {};
        $(".mark_meta_links").unbind('mouseenter mouseleave')
        $(".mark_meta_links").hover(
            function () {
                var markUrl = $(this).find(".mark").attr("href");
                canHideMetaLinks[markUrl] = false;
                $(this).addClass("enable_edit");
            },
            function () {
                var thisJQ = $(this);
                var markUrl = $(this).find(".mark").attr("href");
                canHideMetaLinks[markUrl] = true;
                setTimeout(function(){
                    if (canHideMetaLinks[markUrl]) {
                        thisJQ.removeClass("enable_edit");
                    }
                }, 500);
            }
        );
        $(".copyButton").unbind('click');
        $(".copyButton").click(function(evt) {
            copyMarkToClipboard($(evt.target).closest('.mark_title_line'));
        });
        $(".bookmark .similarButton").unbind('click');
        $(".bookmark .similarButton").click(function(evt) {
            toggleSimilar($(evt.target).closest('.bookmark'));
        });
    }
    registerTitleLineEventHandlers();

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

    function calculateCenter(plot_items) {
        var all_coords = [];
        $.each(plot_items, function(name, coords) {
            // Append coords array to all_coords.
            Array.prototype.push.apply(all_coords, coords);
        });
        const sumLon = all_coords.reduce(function(f, c) { return f+c.lon; }, 0);
        const sumLat = all_coords.reduce(function(f, c) { return f+c.lat; }, 0);
        const centerLon = sumLon / all_coords.length;
        const centerLat = sumLat / all_coords.length;
        return [centerLat, centerLon];
    }

    function map_plot(plot_items) {
        $("#mapwrap").css({display: "block"});

        const zoom=5;
        const center = calculateCenter(plot_items);
        const colors = ["#e00", "#0f0", "#33f", "#ee0", "#c0c", "#0cc",
                        "#f80", "#0fa", "#0af", "#192", "#912", "#12a"];

        const map = L.map('mapdisplay').setView(center, zoom);
        L.tileLayer('https://api.mapbox.com/styles/v1/{id}/tiles/{z}/{x}/{y}?access_token={accessToken}', {
            attribution: '© <a href="https://www.mapbox.com/about/maps/">Mapbox</a> ' +
                         '© <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
                         '<strong><a href="https://www.mapbox.com/map-feedback/" target="_blank">Improve this map</a></strong>',
            tileSize: 512,
            maxZoom: 18,
            zoomOffset: -1,
            id: 'mapbox/outdoors-v11',
            accessToken: 'pk.eyJ1IjoiZ3JlZWswIiwiYSI6IjFDMjFjSWcifQ.7GpHi4dB3TzrBmPKtpdJ6A'
        }).addTo(map);

        let color_index = 0;
        $.each(plot_items, function(name, coords) {
            const color = colors[color_index++ % colors.length];
            $.each(coords, function(i, coord) {
                const marker = L.circleMarker([coord.lat, coord.lon], {
                    title: coord.description,
                    alt: coord.description,
                    fillColor: color,
                    fillOpacity: 1.0,
                    color: "#000",
                    weight: 1,
                    radius: 5,
                });
                const comment = coord.comment.length ? ('<br/>' + coord.comment) : "";
                marker.bindPopup(`
                  <div class="markerContent">[<a href="${coord.mark_href}">${coord.mark_text}</a>]
                    <a href="${coord.href}">${coord.name}</a>${comment}
                  </div>`);
                marker.addTo(map);
            });
        });

        $("#mapclosebtn").click(function(evt) {
            map.remove();
            $("#mapwrap").css({display: "none"});
        });
    }


    $("#loc_parse").click(function(evt) {
        $('head').append(`
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css"
               integrity="sha512-xodZBNTC5n17Xt2atTPuE1HxjVMSvLVW9ocqUKLsCC5CXdbqCmblAshOMAS6/keqq/sMZMZ19scR4PsZChSR7A=="
               crossorigin=""/>
        `);
        $.ajax({
              url: "https://unpkg.com/leaflet@1.7.1/dist/leaflet.js",
              dataType: "script",
              scriptAttrs: {
                  integrity: "sha512-XQoYMqMTK8LvdxXYG3nZ448hOEQiglfqkJs1NOQV44cWnUrBc8PkAOcXy20w0vlaXaVUearIOBhiXZ5V3ynxwA==",
                  crossorigin: "",
              },
              success: () => {
                  // Load all marks where the note contains 'loc:' for processing.
                  const search_url = $("form[action *= 'search']").attr('action');
                  $.get(search_url + "?q=loc:&nopage=1", process_loc_data);
              },
        });
    });

    $("#markdown_zoom_out_btn").click(function(evt) {
        editor.setOption("fontSize", editor.getOption("fontSize") - 2);
    });
    $("#markdown_zoom_in_btn").click(function(evt) {
        editor.setOption("fontSize", editor.getOption("fontSize") + 2);
    });

    $("#markdown_cheatsheet_btn").click(function(evt) {
        $("#markdown_cheatsheet").css({display: "block"});
    });

    if ($("input[type='submit'][value='Save']").length > 0) {
        $(window).bind('keydown', function(evt) {
            var key = String.fromCharCode(evt.which).toLowerCase();
            if ((evt.ctrlKey || evt.metaKey) && key == 's') {
                evt.preventDefault();
                $("input[type='submit'][value='Save']").click();
            }
        });
        $('#note-text').keydown(function (e) {
            if (e.ctrlKey && (e.keyCode == 13 || e.keyCode == 10)) {
                $("input[type='submit'][value='Save']").click();
            }
        });
    }

    function copyMarkToClipboard(titleLineEl) {
        var title_el = titleLineEl.find(".mark_link").first();
        var title = title_el.text();
        var bm_url = titleLineEl.find(".mark").attr("href");
        var link = "[" + title + "](" + bm_url + ")";
        copyToClipboard(link);
        title_el.fadeOut(100).fadeIn(100).fadeOut(100).fadeIn(100);
    }

    function toggleSimilar(bm) {
        var similarEl = bm.find(".similar");
        if (similarEl.html() == "") {
            similarEl.html("Loading similar bookmarks...")
            var url = bm.attr("data-mark-similar-link");
            $.get(url, data => {
                similarEl.html(data);
                registerTitleLineEventHandlers();
            });
        } else {
            similarEl.html("");
        }
    }

    $(window).bind('keydown', function(evt) {
        if (document.activeElement && document.activeElement.tagName == 'INPUT' && document.activeElement.type == 'text') {
            return;  // Don't handle special keypresses if we're in an edit box, let it bubble through.
        }
        if (document.activeElement && document.activeElement.tagName == 'TEXTAREA') {
            return;  // Don't handle special keypresses if we're in the note edit area either.
        }
        if (evt.ctrlKey || evt.altKey || evt.isComposing) {
            return;  // Don't catch any special keyboard combos.
        }

        const key = String.fromCharCode(evt.which).toLowerCase();
        const isSingleBookmark = $("#global-edit-link").length || $(".bookmark").length == 1;
        const bmSelector = isSingleBookmark ? ".bookmark " : ".bookmark:hover ";
        if (key == 'e' && !evt.shiftKey) {
            evt.preventDefault();
            location.href = $(bmSelector + " .local-edit-link").attr('href');
        }
        if (key == 'c' && !evt.shiftKey) {
            evt.preventDefault();
            copyMarkToClipboard($(bmSelector + " .mark_title_line").first());
        }
        if (key == 's' && !evt.shiftKey) {
            evt.preventDefault();
            toggleSimilar($(bmSelector));
        }
        if (key == 's' && evt.shiftKey) {
            evt.preventDefault();
            $(".bookmark").each(function () { toggleSimilar($(this)); });
        }
    });

    class TagAutoComplete {
        constructor(selector, allTags, options) {
            this.selector = selector;
            this.allTags = allTags;
            $(selector)
                .on("keydown", (event) => {
                    // Don't navigate away from the field on tab when selecting an item.
                    if (event.keyCode === $.ui.keyCode.TAB && this.jui.menu.active) {
                        event.preventDefault();
                    }
                    const movementKeys = [$.ui.keyCode.HOME, $.ui.keyCode.END, $.ui.keyCode.LEFT, $.ui.keyCode.RIGHT, $.ui.keyCode.ENTER];
                    if (movementKeys.includes(event.keyCode)) {
                        this.jui.close(event);
                        this.jui.disable();
                    } else {
                        this.jui.enable();
                    }
                })
                .on("blur", (event) => {
                    this.jui.close(event);
                    this.jui.disable();
                })
                .autocomplete({
                    ...options,
                    source: this.source,
                    select: this.select,
                    search: this.search,
                    focus: () => false,  // prevent value inserted on focus
                });
            this.jui = $(selector).autocomplete("instance");
            this.el = $(selector).get(0);
        }
        splitTags = (val) => {
            return val.split(/\s+/);
        }
        getCompletableWord = () => {
            const value = this.el.value;
            if (this.el.selectionStart !== this.el.selectionEnd) {
                return null;  // Text range selected, no good options here...
            }
            if (this.el.selectionStart !== value.length && value[this.el.selectionStart] !== ' ') {
                return null;  // Cursor is within a word, can't offer good suggestions for this.
            }
            const tags = this.splitTags(value.substr(0, this.el.selectionStart));
            return {
                index: tags.length - 1,
                value: tags[tags.length - 1],
            };
        }
        source = (request, response) => {
            console.assert(request.term === this.el.value);
            response($.ui.autocomplete.filter(this.allTags, this.getCompletableWord().value));
        }
        select = (event, ui) => {
            const tags = this.splitTags(this.el.value);
            tags[this.getCompletableWord().index] = ui.item.value;
            tags.push("");  // Add placeholder to get the space at the end
            this.el.value = tags.join(" ");
            return false;
        }
        search = (event, ui) => {
            const cw = this.getCompletableWord();
            if (cw === null || cw.value.length < this.jui.options.minLength) {
                this.jui.close(event);
                return false;
            }
        }
    }
    if ($("#tags-input").length) {
        const allTags = $("#tags-input").attr('data-all-tags').split(' ');
        const tac = new TagAutoComplete("#tags-input", allTags, {minLength: 3, autoFocus: true});
    }
});

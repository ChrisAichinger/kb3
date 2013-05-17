
$(document).ready(function() {
    $(".note").each(function(index, elem) {
        var converter = new Showdown.converter();
        var html = converter.makeHtml($(this).html());
        $(this).html(html);
    });
});

<script>
    /**
     * Shared JavaScript utilities for OpenWrt Admin views.
     * Include this partial at the top of each view that needs these helpers.
     */

    function openwrtAdminCopyToClipboard(text) {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            return navigator.clipboard.writeText(text);
        }

        var deferred = $.Deferred();
        var temp = $("<textarea>")
            .css({position: "fixed", top: "-1000px", left: "-1000px"})
            .val(text)
            .appendTo("body");

        temp.trigger("focus").trigger("select");

        try {
            if (document.execCommand("copy")) {
                deferred.resolve();
            } else {
                deferred.reject();
            }
        } catch (e) {
            deferred.reject(e);
        } finally {
            temp.remove();
        }

        return deferred.promise();
    }

    function openwrtAdminFormatRate(value) {
        if (value === null || value === undefined || value === "") {
            return "n/a";
        }

        var units = ["B/s", "KB/s", "MB/s", "GB/s"];
        var amount = Number(value);
        var unit = 0;
        while (amount >= 1024 && unit < units.length - 1) {
            amount /= 1024;
            unit += 1;
        }
        var decimals = amount >= 100 || unit === 0 ? 0 : 1;
        return amount.toFixed(decimals) + " " + units[unit];
    }

    function openwrtAdminFormatUptime(seconds) {
        if (seconds === null || seconds === undefined) {
            return "n/a";
        }

        var total = Math.max(0, parseInt(seconds, 10) || 0);
        var days = Math.floor(total / 86400);
        var hours = Math.floor((total % 86400) / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        var parts = [];

        if (days > 0) {
            parts.push(days + "d");
        }
        if (hours > 0 || days > 0) {
            parts.push(hours + "h");
        }
        parts.push(minutes + "m");

        return parts.join(" ");
    }

    /**
     * Check broker reachability and show/hide a banner element.
     * @param {string} bannerId  jQuery selector for the banner element, e.g. "#myBanner"
     */
    function openwrtAdminUpdateBrokerBanner(bannerId) {
        ajaxCall("/api/openwrtadmin/service/status/", {}, function(data) {
            var broker = data.broker || null;
            if (broker && broker.ok && broker.body) {
                $(bannerId).addClass("hidden").text("");
                return;
            }

            var serviceState = data.service || "unknown";
            $(bannerId)
                .removeClass("hidden")
                .text(
                    "{{ lang._('The OpenWrt Admin background service is not running (status: ') }}" +
                    serviceState +
                    "{{ lang._('). Go to Services \u2192 OpenWrt Admin to start it.') }}"
                );
        });
    }
</script>

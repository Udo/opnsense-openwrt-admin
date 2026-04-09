{{ partial("OPNsense/OpenWrtAdmin/_js_utils") }}

<script>
    $(document).ready(function() {
        var tbody = $("#openwrtAdminDashboardRows");
        var statusLine = $("#openwrtAdminDashboardStatus");
        var brokerBanner = "#openwrtAdminDashboardBrokerBanner";
        var dhcpDescriptionsByAddress = JSON.parse({{ dhcpDescriptionsByAddressJson|json_encode }});

        function formatLoad(value) {
            return value === null || value === undefined ? "n/a" : Number(value).toFixed(2);
        }

        function formatPercent(value) {
            return value === null || value === undefined ? "n/a" : value + "%";
        }

        function renderWifiClients(router) {
            function renderPlaceholder() {
                return $("<span>", {
                    class: "text-muted",
                    text: "n/a"
                });
            }

            if (!router.wifi_clients_by_network) {
                if (router.wifi_clients === null || router.wifi_clients === undefined) {
                    return renderPlaceholder();
                }
                return $("<span>").text(router.wifi_clients);
            }

            var byNetwork = router.wifi_clients_by_network;
            if (typeof byNetwork === "string") {
                try {
                    byNetwork = JSON.parse(byNetwork);
                } catch (e) {
                    byNetwork = null;
                }
            }

            if (!byNetwork || typeof byNetwork !== "object") {
                return renderPlaceholder();
            }

            var networks = Object.keys(byNetwork).sort();
            if (!networks.length) {
                return renderPlaceholder();
            }

            var wrapper = $("<div>");
            networks.forEach(function(network) {
                wrapper.append(
                    $("<div>", {
                        class: "small"
                    }).append(
                        $("<span>", {
                            class: "text-muted",
                            text: network + ": "
                        })
                    ).append(
                        $("<strong>").text(byNetwork[network])
                    )
                );
            });
            return wrapper;
        }

        function renderSignal(router) {
            function renderSignalPlaceholder() {
                var wrapper = $("<div>");
                var label = $("<div>", {
                    class: "small text-muted",
                    text: "---"
                });
                var bar = $("<div>").css({
                    display: "flex",
                    width: "140px",
                    height: "10px",
                    borderRadius: "999px",
                    overflow: "hidden",
                    background: "#d1d5db",
                    marginTop: "4px"
                });

                wrapper.append(label).append(bar);
                return wrapper;
            }

            if (!router.signal_histogram) {
                return renderSignalPlaceholder();
            }

            var histogram = router.signal_histogram;
            if (typeof histogram === "string") {
                try {
                    histogram = JSON.parse(histogram);
                } catch (e) {
                    histogram = null;
                }
            }

            if (!histogram) {
                return renderSignalPlaceholder();
            }

            var total = ["excellent", "good", "fair", "weak"].reduce(function(sum, key) {
                return sum + (histogram[key] || 0);
            }, 0);

            if (!total) {
                return renderSignalPlaceholder();
            }

            var wrapper = $("<div>");
            var label = $("<div>", {
                class: "small text-muted",
                text: "best " + router.best_signal_dbm + " / worst " + router.worst_signal_dbm + " dBm"
            });
            var bar = $("<div>").css({
                display: "flex",
                width: "140px",
                height: "10px",
                borderRadius: "999px",
                overflow: "hidden",
                background: "#e5e7eb",
                marginTop: "4px"
            });

            [
                {key: "excellent", color: "#22c55e"},
                {key: "good", color: "#84cc16"},
                {key: "fair", color: "#f59e0b"},
                {key: "weak", color: "#ef4444"}
            ].forEach(function(bucket) {
                var count = histogram[bucket.key] || 0;
                if (!count) {
                    return;
                }
                bar.append($("<span>").css({
                    display: "block",
                    width: ((count / total) * 100) + "%",
                    background: bucket.color
                }).attr("title", bucket.key + ": " + count));
            });

            wrapper.append(label).append(bar);
            return wrapper;
        }

        function renderChannels(router) {
            function renderPlaceholder() {
                return $("<span>", {
                    class: "text-muted",
                    text: "n/a"
                });
            }

            if (!router.radio_channels) {
                return renderPlaceholder();
            }

            var values = router.radio_channels;
            if (typeof values === "string") {
                try {
                    values = JSON.parse(values);
                } catch (e) {
                    values = null;
                }
            }

            if (!Array.isArray(values) || !values.length) {
                return renderPlaceholder();
            }

            var wrapper = $("<div>");
            values.forEach(function(entry) {
                wrapper.append(
                    $("<div>", {
                        class: "small",
                        text: entry
                    })
                );
            });
            return wrapper;
        }

        function descriptionFallback(router) {
            if (router.description && String(router.description).trim() !== "") {
                return String(router.description).trim();
            }

            var addressKey = String(router.address || "").toLowerCase();
            return dhcpDescriptionsByAddress[addressKey] || "";
        }

        function renderRows(routers) {
            tbody.empty();

            if (!routers.length) {
                tbody.append(
                    $("<tr>").append(
                        $("<td>", {
                            colspan: 10,
                            class: "text-center text-muted",
                            text: "{{ lang._('No routers registered yet.') }}"
                        })
                    )
                );
                return;
            }

            routers.forEach(function(router) {
                var hostname = router.detected_hostname || router.configured_hostname || "";
                var description = descriptionFallback(router);
                var statusText = router.status_text || "Unknown";
                var statusClass = "label-danger";

                if (router.reachable) {
                    if (statusText.indexOf("Healthy") === 0) {
                        statusText = "ok";
                        statusClass = "label-success";
                    } else if (statusText.indexOf("Warning") === 0) {
                        statusText = "warning";
                        statusClass = "label-warning";
                    } else if (statusText.indexOf("Critical") === 0) {
                        statusText = "critical";
                        statusClass = "label-danger";
                    } else {
                        statusClass = "label-success";
                    }
                }

                tbody.append(
                    $("<tr>")
                        .append($("<td>").text(router.address || ""))
                        .append(
                            $("<td>").append(
                                $("<div>").text(hostname)
                            ).append(
                                description ? $("<div>", {class: "small text-muted", text: description}) : ""
                            )
                        )
                        .append(
                            $("<td>").append(
                                $("<span>", {
                                    class: "label " + statusClass,
                                    text: statusText
                                })
                            )
                        )
                        .append($("<td>").text(formatLoad(router.load_1m)))
                        .append($("<td>").text(openwrtAdminFormatUptime(router.uptime_seconds)))
                        .append($("<td>").text(formatPercent(router.memory_used_pct)))
                        .append($("<td>").append(renderWifiClients(router)))
                        .append($("<td>").append(renderChannels(router)))
                        .append($("<td>").text("rx " + openwrtAdminFormatRate(router.rx_bps) + " / tx " + openwrtAdminFormatRate(router.tx_bps)))
                        .append($("<td>").append(renderSignal(router)))
                );
            });
        }

        function refreshDashboard() {
            openwrtAdminUpdateBrokerBanner(brokerBanner);
            ajaxCall("/api/openwrtadmin/service/routers/", {}, function(data) {
                renderRows(Array.isArray(data.routers) ? data.routers : []);
                statusLine.text("{{ lang._('Updated') }} " + new Date().toLocaleTimeString());
            });
        }

        refreshDashboard();
        window.setInterval(refreshDashboard, 10000);
    });
</script>

<div class="content-box">
    <div class="row">
        <div class="col-xs-12">
            <div class="alert alert-danger hidden" id="openwrtAdminDashboardBrokerBanner"></div>
            <div class="box box-default">
                <div class="box-header with-border">
                    <h3 class="box-title">{{ lang._('Router Overview') }}</h3>
                    <div class="pull-right text-muted" id="openwrtAdminDashboardStatus"></div>
                </div>
                <div class="box-body table-responsive">
                    <table class="table table-striped table-condensed">
                        <thead>
                            <tr>
                                <th>{{ lang._('Address') }}</th>
                                <th>{{ lang._('Hostname') }}</th>
                                <th>{{ lang._('Status') }}</th>
                                <th>{{ lang._('Load') }}</th>
                                <th>{{ lang._('Uptime') }}</th>
                                <th>{{ lang._('Memory Used') }}</th>
                                <th>{{ lang._('WiFi Clients / Network') }}</th>
                                <th>{{ lang._('Channels') }}</th>
                                <th>{{ lang._('Bandwidth') }}</th>
                                <th>{{ lang._('Signal') }}</th>
                            </tr>
                        </thead>
                        <tbody id="openwrtAdminDashboardRows"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>

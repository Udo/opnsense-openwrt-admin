<script>
    $(document).ready(function() {
        const tbody = $("#openwrtAdminDashboardRows");
        const statusLine = $("#openwrtAdminDashboardStatus");
        const brokerBanner = $("#openwrtAdminDashboardBrokerBanner");

        function formatLoad(value) {
            return value === null || value === undefined ? "n/a" : Number(value).toFixed(2);
        }

        function formatPercent(value) {
            return value === null || value === undefined ? "n/a" : value + "%";
        }

        function formatRate(value) {
            if (value === null || value === undefined || value === "") {
                return "n/a";
            }

            const units = ["B/s", "KB/s", "MB/s", "GB/s"];
            let amount = Number(value);
            let unit = 0;
            while (amount >= 1024 && unit < units.length - 1) {
                amount /= 1024;
                unit += 1;
            }
            const decimals = amount >= 100 || unit === 0 ? 0 : 1;
            return amount.toFixed(decimals) + " " + units[unit];
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

            let byNetwork = router.wifi_clients_by_network;
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

            const networks = Object.keys(byNetwork).sort();
            if (!networks.length) {
                return renderPlaceholder();
            }

            const wrapper = $("<div>");
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
                const wrapper = $("<div>");
                const label = $("<div>", {
                    class: "small text-muted",
                    text: "---"
                });
                const bar = $("<div>").css({
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

            let histogram = router.signal_histogram;
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

            const total = ["excellent", "good", "fair", "weak"].reduce(function(sum, key) {
                return sum + (histogram[key] || 0);
            }, 0);

            if (!total) {
                return renderSignalPlaceholder();
            }

            const wrapper = $("<div>");
            const label = $("<div>", {
                class: "small text-muted",
                text: "best " + router.best_signal_dbm + " / worst " + router.worst_signal_dbm + " dBm"
            });
            const bar = $("<div>").css({
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
                const count = histogram[bucket.key] || 0;
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

        function formatUptime(seconds) {
            if (seconds === null || seconds === undefined) {
                return "n/a";
            }

            const total = Math.max(0, parseInt(seconds, 10) || 0);
            const days = Math.floor(total / 86400);
            const hours = Math.floor((total % 86400) / 3600);
            const minutes = Math.floor((total % 3600) / 60);
            const parts = [];

            if (days > 0) {
                parts.push(days + "d");
            }
            if (hours > 0 || days > 0) {
                parts.push(hours + "h");
            }
            parts.push(minutes + "m");

            return parts.join(" ");
        }

        function renderRows(routers) {
            tbody.empty();

            if (!routers.length) {
                tbody.append(
                    $("<tr>").append(
                        $("<td>", {
                            colspan: 9,
                            class: "text-center text-muted",
                            text: "{{ lang._('No routers registered yet.') }}"
                        })
                    )
                );
                return;
            }

            routers.forEach(function(router) {
                const hostname = router.detected_hostname || router.configured_hostname || "";
                let statusText = router.status_text || "Unknown";
                let statusClass = "label-danger";

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
                        .append($("<td>").text(hostname))
                        .append(
                            $("<td>").append(
                                $("<span>", {
                                    class: "label " + statusClass,
                                    text: statusText
                                })
                            )
                        )
                        .append($("<td>").text(formatLoad(router.load_1m)))
                        .append($("<td>").text(formatUptime(router.uptime_seconds)))
                        .append($("<td>").text(formatPercent(router.memory_used_pct)))
                        .append($("<td>").append(renderWifiClients(router)))
                        .append($("<td>").text("rx " + formatRate(router.rx_bps) + " / tx " + formatRate(router.tx_bps)))
                        .append($("<td>").append(renderSignal(router)))
                );
            });
        }

        function updateBrokerBanner() {
            ajaxCall("/api/openwrtadmin/service/status/", {}, function(data) {
                const broker = data.broker || null;
                if (broker && broker.ok && broker.body) {
                    brokerBanner.addClass("hidden").text("");
                    return;
                }

                const serviceState = data.service || "unknown";
                brokerBanner
                    .removeClass("hidden")
                    .text("PHP cannot reach the OpenWrt Admin broker on 127.0.0.1:9783. Service status: " + serviceState + ".");
            });
        }

        function refreshDashboard() {
            updateBrokerBanner();
            ajaxCall("/api/openwrtadmin/service/routers/", {}, function(data) {
                renderRows(Array.isArray(data.routers) ? data.routers : []);
                statusLine.text("Updated " + new Date().toLocaleTimeString());
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

<style>
    .openwrt-admin-client-association {
        margin-bottom: 6px;
    }

    .openwrt-admin-client-association:last-child {
        margin-bottom: 0;
    }

    .openwrt-admin-client-association-meta {
        color: #6b7280;
        font-size: 12px;
    }
</style>

<script>
    $(document).ready(function() {
        const tbody = $("#openwrtAdminClientStatsRows");
        const statusLine = $("#openwrtAdminClientStatsStatus");
        const brokerBanner = $("#openwrtAdminClientStatsBrokerBanner");

        function formatSignal(signal) {
            if (signal === null || signal === undefined || signal === "") {
                return "signal n/a";
            }
            return signal + " dBm";
        }

        function formatRate(value) {
            if (value === null || value === undefined || value === "") {
                return "---";
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

        function formatBytes(value) {
            if (value === null || value === undefined || value === "") {
                return "---";
            }

            const units = ["B", "KB", "MB", "GB", "TB"];
            let amount = Number(value);
            let unit = 0;
            while (amount >= 1024 && unit < units.length - 1) {
                amount /= 1024;
                unit += 1;
            }
            const decimals = amount >= 100 || unit === 0 ? 0 : 1;
            return amount.toFixed(decimals) + " " + units[unit];
        }

        function renderAssociations(client) {
            const wrapper = $("<div>");
            const associations = Array.isArray(client.associations) ? client.associations : [];

            if (!associations.length) {
                return $("<span>", {
                    class: "text-muted",
                    text: "n/a"
                });
            }

            associations.forEach(function(association) {
                const apLabel = association.ap_hostname || association.ap_address || "Unknown AP";
                const networkLabel = association.network_name || association.radio_name || "unknown network";
                wrapper.append(
                    $("<div>", {
                        class: "openwrt-admin-client-association"
                    }).append(
                        $("<div>").append(
                            $("<strong>").text(apLabel)
                        ).append(
                            $("<span>", {
                                text: " - " + formatSignal(association.signal_dbm)
                            })
                        )
                    ).append(
                        $("<div>", {
                            class: "openwrt-admin-client-association-meta",
                            text: networkLabel
                        })
                    ).append(
                        $("<div>", {
                            class: "openwrt-admin-client-association-meta",
                            text: "rx " + formatRate(association.rx_bps) + " / tx " + formatRate(association.tx_bps)
                        })
                    )
                );
            });

            return wrapper;
        }

        function renderRows(clients) {
            tbody.empty();

            if (!clients.length) {
                tbody.append(
                    $("<tr>").append(
                        $("<td>", {
                            colspan: 6,
                            class: "text-center text-muted",
                            text: "{{ lang._('No Wi-Fi clients are currently connected.') }}"
                        })
                    )
                );
                return;
            }

            clients.forEach(function(client) {
                const hostname = client.hostname || "---";
                const ipAddress = client.ip_address || "---";
                const description = client.description_guess || "---";
                const primaryAssociation = Array.isArray(client.associations) && client.associations.length ? client.associations[0] : null;
                const throughput = primaryAssociation
                    ? "rx " + formatRate(primaryAssociation.rx_bps) + " / tx " + formatRate(primaryAssociation.tx_bps)
                    : "---";
                const totals = primaryAssociation
                    ? "rx " + formatBytes(primaryAssociation.rx_bytes) + " / tx " + formatBytes(primaryAssociation.tx_bytes)
                    : "---";

                tbody.append(
                    $("<tr>")
                        .append($("<td>").text(client.mac || ""))
                        .append($("<td>").text(hostname))
                        .append($("<td>").text(ipAddress))
                        .append($("<td>").text(description))
                        .append($("<td>").append(
                            $("<div>").text(throughput),
                            $("<div>", {class: "small text-muted", text: totals})
                        ))
                        .append($("<td>").append(renderAssociations(client)))
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

        function refreshClientStats() {
            updateBrokerBanner();
            ajaxCall("/api/openwrtadmin/service/clients/", {}, function(data) {
                renderRows(Array.isArray(data.clients) ? data.clients : []);
                statusLine.text("Updated " + new Date().toLocaleTimeString());
            });
        }

        refreshClientStats();
        window.setInterval(refreshClientStats, 10000);
    });
</script>

<div class="content-box">
    <div class="row">
        <div class="col-xs-12">
            <div class="alert alert-danger hidden" id="openwrtAdminClientStatsBrokerBanner"></div>
            <div class="box box-default">
                <div class="box-header with-border">
                    <h3 class="box-title">{{ lang._('Client Stats') }}</h3>
                    <div class="box-tools pull-right">
                        <span class="text-muted" id="openwrtAdminClientStatsStatus"></span>
                    </div>
                </div>
                <div class="box-body table-responsive">
                    <table class="table table-striped table-hover">
                        <thead>
                            <tr>
                                <th>{{ lang._('Client MAC') }}</th>
                                <th>{{ lang._('Hostname') }}</th>
                                <th>{{ lang._('IP Address') }}</th>
                                <th>{{ lang._('DHCP Description') }}</th>
                                <th>{{ lang._('Bandwidth') }}</th>
                                <th>{{ lang._('APs / Signal') }}</th>
                            </tr>
                        </thead>
                        <tbody id="openwrtAdminClientStatsRows">
                            <tr>
                                <td colspan="6" class="text-center text-muted">{{ lang._('Loading client data...') }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>

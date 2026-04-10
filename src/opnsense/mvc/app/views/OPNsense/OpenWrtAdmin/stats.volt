<script src="/ui/js/moment-with-locales.min.js"></script>
<script src="/ui/js/chart.umd.min.js"></script>
<script src="/ui/js/chartjs-adapter-moment.min.js"></script>
{{ partial("OPNsense/OpenWrtAdmin/_js_utils") }}

<style>
    .openwrt-admin-stats-toolbar {
        margin-bottom: 18px;
    }

    .openwrt-admin-stats-toolbar .help-block {
        margin-bottom: 0;
    }

    .openwrt-admin-stats-toolbar .form-group {
        margin-bottom: 12px;
    }

    .openwrt-admin-stats-presets {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 6px;
    }

    .openwrt-admin-stats-chart-wrap {
        position: relative;
        min-height: 320px;
    }

    .openwrt-admin-stats-empty {
        padding: 18px 0 4px;
    }

    .openwrt-admin-stats-chart-note {
        color: #6b7280;
        font-size: 12px;
        margin-top: 8px;
    }

    .openwrt-admin-stats-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
    }

    .openwrt-admin-stats-filter-select + .bootstrap-select {
        width: 100% !important;
    }
</style>

<script>
    $(document).ready(function() {
        var brokerBanner = "#openwrtAdminStatsBrokerBanner";
        var statusLine = $("#openwrtAdminStatsStatus");
        var emptyState = $("#openwrtAdminStatsEmpty");
        var clientsChart;
        var signalChart;

        function formatLocalInputValue(date) {
            function pad(value) {
                return String(value).padStart(2, "0");
            }

            return date.getFullYear() + "-" +
                pad(date.getMonth() + 1) + "-" +
                pad(date.getDate()) + "T" +
                pad(date.getHours()) + ":" +
                pad(date.getMinutes());
        }

        function parseLocalInputToIso(value) {
            if (!value) {
                return "";
            }

            var date = new Date(value);
            if (isNaN(date.getTime())) {
                return "";
            }
            return date.toISOString();
        }

        function currentFilters() {
            return {
                start_at: parseLocalInputToIso($("#openwrtAdminStatsStartAt").val()),
                end_at: parseLocalInputToIso($("#openwrtAdminStatsEndAt").val()),
                routers: $("#openwrtAdminStatsRouters").val() || [],
                networks: $("#openwrtAdminStatsNetworks").val() || []
            };
        }

        function formatDateTime(value) {
            if (!value) {
                return "---";
            }
            var date = new Date(value);
            if (isNaN(date.getTime())) {
                return value;
            }
            return date.toLocaleString();
        }

        function colorForIndex(index, alpha) {
            var hue = (index * 67) % 360;
            var opacity = alpha === undefined ? 1 : alpha;
            return "hsla(" + hue + ", 68%, 44%, " + opacity + ")";
        }

        function applyOptions(select, items, selectedValues, valueKey, labelBuilder) {
            var currentSelection = Array.isArray(selectedValues) ? selectedValues.slice() : [];
            var previousSelection = $(select).val() || [];
            if (!currentSelection.length) {
                currentSelection = previousSelection;
            }

            $(select).empty();
            items.forEach(function(item) {
                var value = String(item[valueKey] || "");
                if (!value) {
                    return;
                }

                $("<option>", {
                    value: value,
                    text: labelBuilder(item),
                    selected: currentSelection.indexOf(value) !== -1
                }).appendTo(select);
            });

            $(select).selectpicker("refresh");
        }

        function buildClientDatasets(rows) {
            var grouped = {};
            rows.forEach(function(row) {
                var network = row.network_name || "{{ lang._('Unknown network') }}";
                if (!grouped[network]) {
                    grouped[network] = [];
                }
                grouped[network].push({
                    x: row.hour_bucket,
                    y: row.avg_clients
                });
            });

            return Object.keys(grouped).sort().map(function(network, index) {
                return {
                    label: network,
                    data: grouped[network],
                    borderColor: colorForIndex(index, 0.95),
                    backgroundColor: colorForIndex(index, 0.18),
                    borderWidth: 2,
                    pointRadius: 1.5,
                    pointHoverRadius: 4,
                    tension: 0.2,
                    fill: false
                };
            });
        }

        function buildSignalDatasets(rows) {
            var grouped = {};
            rows.forEach(function(row) {
                var network = row.network_name || "{{ lang._('Unknown network') }}";
                if (!grouped[network]) {
                    grouped[network] = {
                        avg: [],
                        best: [],
                        worst: []
                    };
                }

                grouped[network].avg.push({x: row.hour_bucket, y: row.avg_signal_dbm});
                grouped[network].best.push({x: row.hour_bucket, y: row.best_signal_dbm});
                grouped[network].worst.push({x: row.hour_bucket, y: row.worst_signal_dbm});
            });

            var datasets = [];
            Object.keys(grouped).sort().forEach(function(network, index) {
                var base = colorForIndex(index, 1);
                datasets.push({
                    label: network + " avg",
                    data: grouped[network].avg,
                    borderColor: base,
                    backgroundColor: colorForIndex(index, 0.16),
                    borderWidth: 2.4,
                    pointRadius: 1.2,
                    pointHoverRadius: 4,
                    tension: 0.2,
                    spanGaps: true,
                    fill: false
                });
                datasets.push({
                    label: network + " best",
                    data: grouped[network].best,
                    borderColor: colorForIndex(index, 0.55),
                    borderDash: [7, 4],
                    borderWidth: 1.8,
                    pointRadius: 0,
                    pointHoverRadius: 3,
                    tension: 0.2,
                    spanGaps: true,
                    fill: false
                });
                datasets.push({
                    label: network + " worst",
                    data: grouped[network].worst,
                    borderColor: colorForIndex(index, 0.38),
                    borderDash: [2, 4],
                    borderWidth: 1.8,
                    pointRadius: 0,
                    pointHoverRadius: 3,
                    tension: 0.2,
                    spanGaps: true,
                    fill: false
                });
            });

            return datasets;
        }

        function ensureCharts() {
            if (!clientsChart) {
                clientsChart = new Chart(document.getElementById("openwrtAdminClientsChart"), {
                    type: "line",
                    data: {datasets: []},
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        interaction: {
                            mode: "nearest",
                            intersect: false
                        },
                        plugins: {
                            legend: {
                                position: "bottom"
                            }
                        },
                        scales: {
                            x: {
                                type: "time",
                                bounds: "ticks",
                                time: {
                                    tooltipFormat: "YYYY-MM-DD HH:mm",
                                    round: "hour",
                                    displayFormats: {
                                        hour: "MMM D HH:mm",
                                        day: "MMM D"
                                    }
                                },
                                title: {
                                    display: true,
                                    text: "{{ lang._('Time') }}"
                                }
                            },
                            y: {
                                beginAtZero: true,
                                title: {
                                    display: true,
                                    text: "{{ lang._('Clients') }}"
                                }
                            }
                        }
                    }
                });
            }

            if (!signalChart) {
                signalChart = new Chart(document.getElementById("openwrtAdminSignalChart"), {
                    type: "line",
                    data: {datasets: []},
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        interaction: {
                            mode: "nearest",
                            intersect: false
                        },
                        plugins: {
                            legend: {
                                position: "bottom"
                            }
                        },
                        scales: {
                            x: {
                                type: "time",
                                bounds: "ticks",
                                time: {
                                    tooltipFormat: "YYYY-MM-DD HH:mm",
                                    round: "hour",
                                    displayFormats: {
                                        hour: "MMM D HH:mm",
                                        day: "MMM D"
                                    }
                                },
                                title: {
                                    display: true,
                                    text: "{{ lang._('Time') }}"
                                }
                            },
                            y: {
                                reverse: false,
                                suggestedMin: -90,
                                suggestedMax: -35,
                                title: {
                                    display: true,
                                    text: "{{ lang._('Signal (dBm)') }}"
                                }
                            }
                        }
                    }
                });
            }
        }

        function applyPreset(days) {
            var end = new Date();
            var start = new Date(end.getTime() - (days * 24 * 60 * 60 * 1000));
            $("#openwrtAdminStatsEndAt").val(formatLocalInputValue(end));
            $("#openwrtAdminStatsStartAt").val(formatLocalInputValue(start));
        }

        function renderStats(data) {
            var rows = Array.isArray(data.rows) ? data.rows : [];
            ensureCharts();

            clientsChart.data.datasets = buildClientDatasets(rows);
            clientsChart.options.scales.x.min = data.start_at || null;
            clientsChart.options.scales.x.max = data.end_at || null;
            clientsChart.update("none");

            signalChart.data.datasets = buildSignalDatasets(rows);
            signalChart.options.scales.x.min = data.start_at || null;
            signalChart.options.scales.x.max = data.end_at || null;
            signalChart.update("none");

            if (!rows.length) {
                emptyState.removeClass("hidden").text("{{ lang._('No hourly stats are available for the current filters yet.') }}");
            } else {
                emptyState.addClass("hidden").text("");
            }

            applyOptions(
                "#openwrtAdminStatsRouters",
                Array.isArray(data.routers) ? data.routers : [],
                data.selected_routers || [],
                "router_uuid",
                function(item) {
                    return item.label || item.address || item.router_uuid;
                }
            );
            applyOptions(
                "#openwrtAdminStatsNetworks",
                Array.isArray(data.networks) ? data.networks : [],
                data.selected_networks || [],
                "name",
                function(item) {
                    return item.name;
                }
            );

            statusLine.text("{{ lang._('Updated') }} " + new Date().toLocaleTimeString());
        }

        function loadStats() {
            openwrtAdminUpdateBrokerBanner(brokerBanner);
            ajaxCall("/api/openwrtadmin/service/stats/", currentFilters(), function(data) {
                renderStats(data);
            });
        }

        $("#openwrtAdminStatsApply").click(function() {
            loadStats();
        });

        $("#openwrtAdminStatsReset").click(function() {
            $("#openwrtAdminStatsRouters").val([]);
            $("#openwrtAdminStatsNetworks").val([]);
            applyPreset(7);
            loadStats();
        });

        $(".openwrtAdminStatsPreset").click(function() {
            applyPreset(parseInt($(this).data("days"), 10) || 7);
            loadStats();
        });

        applyPreset(7);
        $(".openwrt-admin-stats-filter-select").selectpicker({
            selectedTextFormat: "count > 2",
            countSelectedText: function(selected, total) {
                return selected + " / " + total + " selected";
            },
            noneSelectedText: "{{ lang._('All') }}",
            liveSearch: true,
            actionsBox: true,
            width: "100%"
        });

        loadStats();
    });
</script>

<div class="content-box">
    <div class="row">
        <div class="col-xs-12">
            <div class="alert alert-danger hidden" id="openwrtAdminStatsBrokerBanner"></div>
            <div class="box box-default">
                <div class="box-header with-border">
                    <h3 class="box-title">{{ lang._('Wi-Fi History') }}</h3>
                    <div class="box-tools pull-right">
                        <span class="text-muted" id="openwrtAdminStatsStatus"></span>
                    </div>
                </div>
                <div class="box-body">
                    <div class="row openwrt-admin-stats-toolbar">
                        <div class="col-sm-3">
                            <div class="form-group">
                            <label for="openwrtAdminStatsRouters">{{ lang._('AP Filter') }}</label>
                            <select class="selectpicker openwrt-admin-stats-filter-select" id="openwrtAdminStatsRouters" multiple data-actions-box="true" data-live-search="true" data-selected-text-format="count > 2" title="{{ lang._('All APs') }}"></select>
                            </div>
                        </div>
                        <div class="col-sm-3">
                            <div class="form-group">
                            <label for="openwrtAdminStatsNetworks">{{ lang._('Wi-Fi Networks') }}</label>
                            <select class="selectpicker openwrt-admin-stats-filter-select" id="openwrtAdminStatsNetworks" multiple data-actions-box="true" data-live-search="true" data-selected-text-format="count > 2" title="{{ lang._('All networks') }}"></select>
                            </div>
                        </div>
                        <div class="col-sm-2">
                            <div class="form-group">
                            <label for="openwrtAdminStatsStartAt">{{ lang._('Start') }}</label>
                            <input class="form-control" id="openwrtAdminStatsStartAt" type="datetime-local" />
                            </div>
                        </div>
                        <div class="col-sm-2">
                            <div class="form-group">
                            <label for="openwrtAdminStatsEndAt">{{ lang._('End') }}</label>
                            <input class="form-control" id="openwrtAdminStatsEndAt" type="datetime-local" />
                            </div>
                        </div>
                        <div class="col-sm-2">
                            <div class="form-group">
                            <label>{{ lang._('Actions') }}</label>
                            <div class="openwrt-admin-stats-actions">
                                <button class="btn btn-primary" id="openwrtAdminStatsApply" type="button">{{ lang._('Apply') }}</button>
                                <button class="btn btn-default" id="openwrtAdminStatsReset" type="button">{{ lang._('Reset') }}</button>
                            </div>
                            <div class="openwrt-admin-stats-presets">
                                <button class="btn btn-xs btn-default openwrtAdminStatsPreset" data-days="1" type="button">{{ lang._('24h') }}</button>
                                <button class="btn btn-xs btn-default openwrtAdminStatsPreset" data-days="7" type="button">{{ lang._('7d') }}</button>
                                <button class="btn btn-xs btn-default openwrtAdminStatsPreset" data-days="30" type="button">{{ lang._('30d') }}</button>
                                <button class="btn btn-xs btn-default openwrtAdminStatsPreset" data-days="90" type="button">{{ lang._('90d') }}</button>
                            </div>
                            </div>
                        </div>
                    </div>

                    <hr />

                    <div class="box box-default">
                        <div class="box-header with-border">
                            <h3 class="box-title">{{ lang._('Clients per Wi-Fi Network') }}</h3>
                        </div>
                        <div class="box-body">
                            <div class="openwrt-admin-stats-chart-wrap">
                                <canvas id="openwrtAdminClientsChart"></canvas>
                            </div>
                            <div class="openwrt-admin-stats-chart-note">{{ lang._('Each line shows the hourly average number of currently associated clients for one Wi-Fi network.') }}</div>
                        </div>
                    </div>

                    <div class="box box-default">
                        <div class="box-header with-border">
                            <h3 class="box-title">{{ lang._('Signal Strength') }}</h3>
                        </div>
                        <div class="box-body">
                            <div class="openwrt-admin-stats-chart-wrap">
                                <canvas id="openwrtAdminSignalChart"></canvas>
                            </div>
                            <div class="openwrt-admin-stats-chart-note">{{ lang._('Average signal is shown as a solid line; best and worst observed client signal per hour are dashed.') }}</div>
                        </div>
                    </div>

                    <div class="text-center text-muted openwrt-admin-stats-empty hidden" id="openwrtAdminStatsEmpty"></div>
                </div>
            </div>
        </div>
    </div>
</div>

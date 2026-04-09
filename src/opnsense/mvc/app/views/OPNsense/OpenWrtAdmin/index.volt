{{ partial("OPNsense/OpenWrtAdmin/_js_utils") }}

<script>
    $(document).ready(function() {
        var editDialogId = "#{{ formGridRouter['edit_dialog_id'] }}";
        var gridId = "#{{ formGridRouter['table_id'] }}";
        var sshKeyFieldId = "router\\.ssh_key_ref";
        var configSyncFields = [
            {type: "wifi", fieldId: "router\\.sync_wifi_config_from", restoreLabel: "{{ lang._('Restore Wi-Fi backup') }}"},
            {type: "system", fieldId: "router\\.sync_system_config_from", restoreLabel: "{{ lang._('Restore system backup') }}"},
            {type: "firewall", fieldId: "router\\.sync_firewall_config_from", restoreLabel: "{{ lang._('Restore firewall backup') }}"},
            {type: "dhcp", fieldId: "router\\.sync_dhcp_config_from", restoreLabel: "{{ lang._('Restore DHCP backup') }}"},
            {type: "rpcd", fieldId: "router\\.sync_rpcd_config_from", restoreLabel: "{{ lang._('Restore authentication (rpcd) backup') }}"}
        ];
        var routerAddressFieldId = "router\\.address";
        var routerStatusFieldId = "router\\.status";
        var routerVersionFieldId = "router\\.version";
        var routerHardwareFieldId = "router\\.hardware";
        var routerSyncStatusFieldId = "router\\.sync_status";
        var brokerBannerId = "#openwrtAdminBrokerBanner";
        var bulkActionStatusId = "#openwrtAdminBulkActionStatus";
        var bulkActionButtonIds = "#bulkSyncRoutersBtn, #bulkSysUpdateBtn, #bulkRebootRoutersBtn, #bulkRadiosOnBtn, #bulkRadiosOffBtn, #bulkRoamingBaselineBtn";
        var currentEditRouterUuid = null;
        var runtimeRouters = [];

        function updateCopyButtonState() {
            var hasValue = $("#" + sshKeyFieldId).val() !== "";
            $("#copySshPublicKeyBtn").prop("disabled", !hasValue);
            $("#openRouterSshKeysPageBtn").prop("disabled", $("#" + routerAddressFieldId).val() === "");
        }

        function ensureCopyButton() {
            var target = $("#select_" + sshKeyFieldId);
            if (target.length === 0 || $("#copySshPublicKeyBtn").length > 0) {
                updateCopyButtonState();
                return;
            }

            target.append(
                '<div class="top-padding">' +
                    '<button type="button" class="btn btn-default btn-xs" id="copySshPublicKeyBtn">' +
                        '<span class="fa fa-clipboard fa-fw"></span>{{ lang._("Copy Public Key") }}' +
                    '</button> ' +
                    '<button type="button" class="btn btn-default btn-xs" id="openRouterSshKeysPageBtn">' +
                        '<span class="fa fa-external-link fa-fw"></span>{{ lang._("Open SSH Keys Page") }}' +
                    '</button> ' +
                    '<span id="copySshPublicKeyStatus" class="text-muted"></span>' +
                '</div>'
            );
            updateCopyButtonState();
        }

        function ensureRestoreControls() {
            configSyncFields.forEach(function(config) {
                var target = $("#select_" + config.fieldId);
                if (target.length === 0 || $("#restore" + config.type + "BackupBtn").length > 0) {
                    return;
                }

                target.append(
                    '<div class="top-padding openwrtAdminRestoreBlock" data-config-type="' + config.type + '">' +
                        '<label class="control-label">' + config.restoreLabel + '</label>' +
                        '<div class="input-group input-group-sm">' +
                            '<select class="form-control openwrtAdminRestoreBackupSelect" id="openwrtAdminRestoreBackupSelect_' + config.type + '" data-config-type="' + config.type + '"></select>' +
                            '<span class="input-group-btn">' +
                                '<button type="button" class="btn btn-default openwrtAdminRestoreBackupBtn" id="restore' + config.type + 'BackupBtn" data-config-type="' + config.type + '">{{ lang._("Restore") }}</button>' +
                            '</span>' +
                        '</div>' +
                        '<div class="text-muted small top-padding openwrtAdminRestoreBackupStatus" id="openwrtAdminRestoreBackupStatus_' + config.type + '"></div>' +
                    '</div>'
                );
            });
        }

        function loadRuntimeRouters(callback) {
            ajaxCall("/api/openwrtadmin/service/routers/", {}, function(data) {
                runtimeRouters = Array.isArray(data.routers) ? data.routers : [];
                if (typeof callback === "function") {
                    callback(runtimeRouters);
                }
            });
        }

        function currentRuntimeRouter() {
            var address = $("#" + routerAddressFieldId).val();
            var current = null;
            if (currentEditRouterUuid) {
                current = runtimeRouters.find(function(item) {
                    return item.router_uuid === currentEditRouterUuid;
                }) || null;
            }
            if (!current && address) {
                current = runtimeRouters.find(function(item) {
                    return item.address === address;
                }) || null;
            }
            return current;
        }

        function effectiveEditRouterUuid() {
            if (currentEditRouterUuid) {
                return currentEditRouterUuid;
            }

            var current = currentRuntimeRouter();
            if (current && current.router_uuid) {
                currentEditRouterUuid = current.router_uuid;
                return currentEditRouterUuid;
            }

            return null;
        }

        function updateSyncSourceOptions() {
            configSyncFields.forEach(function(config) {
                var select = $("#" + config.fieldId);
                if (!select.length) {
                    return;
                }

                if (!select.data("all-options")) {
                    var allOptions = [];
                    select.find("option").each(function() {
                        allOptions.push({
                            value: $(this).attr("value") || "",
                            label: $(this).text()
                        });
                    });
                    select.data("all-options", allOptions);
                }

                var current = currentRuntimeRouter();
                var currentModel = current && current.hardware_model ? current.hardware_model : "";
                var selectedValue = select.val() || "";
                var runtimeByUuid = {};
                runtimeRouters.forEach(function(item) {
                    if (item.router_uuid) {
                        runtimeByUuid[item.router_uuid] = item;
                    }
                });

                select.empty();
                (select.data("all-options") || []).forEach(function(option) {
                    if (option.value === "") {
                        select.append($("<option>").attr("value", "").text(option.label));
                        return;
                    }

                    var editingUuid = effectiveEditRouterUuid();
                    if (editingUuid && option.value === editingUuid) {
                        return;
                    }

                    var candidate = runtimeByUuid[option.value] || null;
                    if (currentModel !== "" && (!candidate || candidate.hardware_model !== currentModel)) {
                        return;
                    }

                    select.append($("<option>").attr("value", option.value).text(option.label));
                });

                if (select.find("option[value='" + selectedValue + "']").length > 0) {
                    select.val(selectedValue);
                } else {
                    select.val("");
                }

                if (select.hasClass("selectpicker")) {
                    select.selectpicker("refresh");
                }
            });
        }

        function formatBackupLabel(item) {
            var ts = item.last_seen_at || item.created_at || "";
            var date = ts ? new Date(ts).toLocaleString() : "?";
            var hash = (item.content_hash || "").slice(0, 12);
            var bytes = item.size_bytes || 0;
            var size;
            if (bytes >= 1048576) {
                size = (bytes / 1048576).toFixed(1) + " MB";
            } else if (bytes >= 1024) {
                size = (bytes / 1024).toFixed(1) + " KB";
            } else {
                size = bytes + " B";
            }
            return date + " \u2014 " + hash + " \u2014 " + size;
        }

        function loadRestoreBackups(configType) {
            var backupSelect = $("#openwrtAdminRestoreBackupSelect_" + configType);
            var backupStatus = $("#openwrtAdminRestoreBackupStatus_" + configType);
            var restoreButton = $("#restore" + configType + "BackupBtn");

            if (!backupSelect.length) {
                return;
            }

            var routerUuid = effectiveEditRouterUuid();
            if (!routerUuid) {
                backupSelect.empty().append($("<option>").text("{{ lang._('Save the router first to enable restore.') }}"));
                restoreButton.prop("disabled", true);
                backupStatus.text("");
                return;
            }

            backupStatus.text("{{ lang._('Loading backups...') }}");
            ajaxCall("/api/openwrtadmin/service/config_backups/", {router_uuid: routerUuid, config_type: configType}, function(data) {
                backupSelect.empty();
                var backups = Array.isArray(data.backups) ? data.backups : [];
                if (!backups.length) {
                    backupSelect.append($("<option>").text("{{ lang._('No backups stored yet.') }}").attr("value", ""));
                    restoreButton.prop("disabled", true);
                    backupStatus.text("");
                    return;
                }

                backups.forEach(function(item) {
                    backupSelect.append($("<option>").attr("value", item.content_hash).text(formatBackupLabel(item)));
                });
                restoreButton.prop("disabled", false);
                backupStatus.text("");
            });
        }

        function hideLiveStatusFields() {
            $("#" + routerStatusFieldId).closest(".form-group, tr").hide();
            $("#" + routerVersionFieldId).closest(".form-group, tr").hide();
            $("#" + routerHardwareFieldId).closest(".form-group, tr").hide();
            $("#" + routerSyncStatusFieldId).closest(".form-group, tr").hide();
        }

        function selectedRouterIds() {
            return $(gridId).bootgrid("getSelectedRows") || [];
        }

        function routerRowData(rowId) {
            var bootgrid = $(gridId).data("UIBootgrid");
            if (bootgrid && bootgrid.table) {
                var row = bootgrid.table.getRow(rowId);
                if (row) {
                    return row.getData();
                }
            }

            return runtimeRouters.find(function(item) {
                return item.router_uuid === rowId;
            }) || null;
        }

        function updateBulkActionButtons() {
            $(bulkActionButtonIds).prop("disabled", selectedRouterIds().length === 0);
        }

        function setBulkActionStatus(message, level) {
            var node = $(bulkActionStatusId);
            node.removeClass("alert alert-danger alert-info alert-success hidden");
            if (!message) {
                node.addClass("hidden").text("");
                return;
            }

            var cssClass = level === "success"
                ? "alert alert-success"
                : level === "error"
                    ? "alert alert-danger"
                    : "alert alert-info";
            node.addClass(cssClass).text(message);
        }

        function updateBulkActionIcons() {
            $("#bulkRadiosOnBtn span").removeClass().text("on");
            $("#bulkRadiosOffBtn span").removeClass().text("off");
        }

        function performBulkAction(action, title, prompt) {
            var routers = selectedRouterIds();
            if (!routers.length) {
                setBulkActionStatus("{{ lang._('Select at least one router.') }}", "error");
                updateBulkActionButtons();
                return;
            }

            stdDialogConfirm(title, prompt, "{{ lang._('Yes') }}", "{{ lang._('Cancel') }}", function() {
                setBulkActionStatus("{{ lang._('Running') }} " + title.toLowerCase() + "...", "info");
                $(bulkActionButtonIds).prop("disabled", true);
                ajaxCall("/api/openwrtadmin/service/bulk_action/", {action: action, routers: routers}, function(data) {
                    var failed = Array.isArray(data.results)
                        ? data.results.filter(function(item) { return !item.ok; })
                        : [];

                    if ((data.status || "") !== "ok") {
                        setBulkActionStatus(data.message || "{{ lang._('Bulk action failed.') }}", "error");
                    } else if (failed.length) {
                        var details = failed.map(function(item) {
                            return (item.address || item.router_uuid || "router") + ": " + (item.message || "error");
                        }).join("; ");
                        setBulkActionStatus((data.successful || 0) + " {{ lang._('ok') }}, " + failed.length + " {{ lang._('failed.') }} " + details, "error");
                    } else if (action === "sync_configs") {
                        setBulkActionStatus((data.changed || 0) + " {{ lang._('router(s) synced.') }}", "success");
                    } else if (action === "sys_update") {
                        setBulkActionStatus((data.successful || 0) + " {{ lang._('router(s) updated with system packages.') }}", "success");
                    } else if (action === "apply_roaming_baseline") {
                        setBulkActionStatus((data.successful || 0) + " {{ lang._('router(s) updated with the roaming baseline.') }}", "success");
                    } else {
                        setBulkActionStatus((data.successful || 0) + " {{ lang._('router(s) updated.') }}", "success");
                    }

                    updateBulkActionButtons();
                    window.setTimeout(function() {
                        $(gridId).bootgrid("reload");
                    }, 1000);
                });
            });
        }

        $(gridId).UIBootgrid({
            search: "/api/openwrtadmin/settings/search_router/",
            get: "/api/openwrtadmin/settings/get_router/",
            set: "/api/openwrtadmin/settings/set_router/",
            add: "/api/openwrtadmin/settings/add_router/",
            del: "/api/openwrtadmin/settings/del_router/",
            commands: {
                openui: {
                    method: function(event) {
                        var rowId = $(event.currentTarget).data("row-id");
                        var row = routerRowData(rowId);
                        var address = row && row.address ? row.address : "";
                        if (!address) {
                            return;
                        }

                        window.open("http://" + address + "/cgi-bin/luci/admin", "_blank", "noopener");
                    },
                    classname: "fa fa-fw fa-external-link",
                    title: "{{ lang._('Open router admin UI') }}",
                    sequence: 50
                }
            },
            options: {
                selection: true,
                multiSelect: true,
                rowSelect: true,
                keepSelection: true,
                formatters: {
                    sync_status: function(column, row) {
                        var value = row.sync_status || "";
                        if (!value) {
                            return "";
                        }
                        if (row.sync_in_sync === "1") {
                            return $("<span>", {
                                class: "label label-success",
                                text: value
                            })[0].outerHTML;
                        }
                        return $("<span>", {
                            class: "text-muted",
                            text: value
                        })[0].outerHTML;
                    }
                }
            }
        }).on("loaded.rs.jquery.bootgrid selected.rs.jquery.bootgrid deselected.rs.jquery.bootgrid", function() {
            updateBulkActionIcons();
            updateBulkActionButtons();
        });

        openwrtAdminUpdateBrokerBanner(brokerBannerId);
        updateBulkActionIcons();
        updateBulkActionButtons();
        loadRuntimeRouters();

        window.setInterval(function() {
            openwrtAdminUpdateBrokerBanner(brokerBannerId);
            if (!$(editDialogId).is(":visible")) {
                $(gridId).bootgrid("reload");
            }
        }, 60000);

        $(document).on("shown.bs.modal", editDialogId, function() {
            ensureCopyButton();
            ensureRestoreControls();
            hideLiveStatusFields();
            $("#" + sshKeyFieldId).selectpicker("refresh");
            updateCopyButtonState();
            loadRuntimeRouters(function() {
                updateSyncSourceOptions();
                configSyncFields.forEach(function(config) {
                    loadRestoreBackups(config.type);
                });
            });
        });

        $(document).on("click", gridId + " .command-edit", function() {
            currentEditRouterUuid = $(this).data("row-id") || null;
            $(".openwrtAdminRestoreBackupStatus").text("");
        });

        $(document).on("click", gridId + " [data-action=add]", function() {
            currentEditRouterUuid = null;
            $(".openwrtAdminRestoreBackupStatus").text("");
        });

        $(document).on("change", "#" + sshKeyFieldId, function() {
            $("#copySshPublicKeyStatus").text("");
            updateCopyButtonState();
        });

        $(document).on("input change", "#" + routerAddressFieldId, function() {
            updateCopyButtonState();
        });

        $(document).on("change", configSyncFields.map(function(config) { return "#" + config.fieldId; }).join(", "), function() {
            $(".openwrtAdminRestoreBackupStatus").text("");
        });

        $(document).on("click", "#copySshPublicKeyBtn", function() {
            var ref = $("#" + sshKeyFieldId).val();
            if (!ref) {
                $("#copySshPublicKeyStatus").text("{{ lang._('No key selected.') }}");
                updateCopyButtonState();
                return;
            }

            ajaxCall("/api/openwrtadmin/settings/get_ssh_public_key/", {ref: ref}, function(data) {
                if (data.status !== "ok" || !data.public_key) {
                    $("#copySshPublicKeyStatus").text("{{ lang._('Unable to load key.') }}");
                    return;
                }

                openwrtAdminCopyToClipboard(data.public_key).then(function() {
                    $("#copySshPublicKeyStatus").text("{{ lang._('Copied.') }}");
                }).catch(function() {
                    $("#copySshPublicKeyStatus").text("{{ lang._('Clipboard access failed.') }}");
                });
            });
        });

        $(document).on("click", "#openRouterSshKeysPageBtn", function() {
            var address = $("#" + routerAddressFieldId).val();
            if (!address) {
                $("#copySshPublicKeyStatus").text("{{ lang._('No router address set.') }}");
                updateCopyButtonState();
                return;
            }

            var url = "http://" + address + "/cgi-bin/luci/admin/system/admin/sshkeys";
            window.open(url, "_blank", "noopener");
        });

        $(document).on("click", "#bulkRebootRoutersBtn", function() {
            performBulkAction("reboot", "{{ lang._('Reboot routers') }}", "{{ lang._('Reboot the selected routers?') }}");
        });

        $(document).on("click", "#bulkRadiosOnBtn", function() {
            performBulkAction("radios_on", "{{ lang._('Enable radios') }}", "{{ lang._('Enable Wi-Fi radios on the selected routers?') }}");
        });

        $(document).on("click", "#bulkRadiosOffBtn", function() {
            performBulkAction("radios_off", "{{ lang._('Disable radios') }}", "{{ lang._('Disable Wi-Fi radios on the selected routers?') }}");
        });

        $(document).on("click", "#bulkRoamingBaselineBtn", function() {
            performBulkAction("apply_roaming_baseline", "{{ lang._('Apply roaming baseline') }}", "{{ lang._('Install usteer and apply the roaming baseline on the selected routers?') }}");
        });

        $(document).on("click", "#bulkSyncRoutersBtn", function() {
            performBulkAction("sync_configs", "{{ lang._('Sync configs') }}", "{{ lang._('Sync configs on the selected routers where needed?') }}");
        });

        $(document).on("click", "#bulkSysUpdateBtn", function() {
            performBulkAction("sys_update", "{{ lang._('System update') }}", "{{ lang._('Run apk update and apk upgrade on the selected routers?') }}");
        });

        $(document).on("click", ".openwrtAdminRestoreBackupBtn", function() {
            var configType = $(this).data("config-type");
            var contentHash = $("#openwrtAdminRestoreBackupSelect_" + configType).val();
            var statusSelector = "#openwrtAdminRestoreBackupStatus_" + configType;
            var prettyType = configType === "wifi" ? "Wi-Fi" : configType;
            var routerUuid = effectiveEditRouterUuid();
            if (!routerUuid || !contentHash) {
                $(statusSelector).text("{{ lang._('No backup selected.') }}");
                return;
            }

            stdDialogConfirm(
                "{{ lang._('Restore backup') }}",
                "{{ lang._('Restore the selected backup to this router? The current config will be overwritten.') }}",
                "{{ lang._('Yes') }}",
                "{{ lang._('Cancel') }}",
                function() {
                    $(statusSelector).text("{{ lang._('Restoring backup...') }}");
                    ajaxCall("/api/openwrtadmin/service/restore_config_backup/", {
                        router_uuid: routerUuid,
                        config_type: configType,
                        content_hash: contentHash
                    }, function(data) {
                        $(statusSelector).text(data.message || "{{ lang._('Restore completed.') }}");
                        loadRestoreBackups(configType);
                        loadRuntimeRouters();
                        window.setTimeout(function() {
                            $(gridId).bootgrid("reload");
                        }, 1000);
                    });
                }
            );
        });
    });
</script>

<div class="content-box">
    <div class="alert alert-warning hidden" id="openwrtAdminBrokerBanner"></div>
    <div class="hidden" id="openwrtAdminBulkActionStatus"></div>
    {{ partial('layout_partials/base_bootgrid_table', formGridRouter + {
        'command_width': '135'
    }) }}
    <div class="panel panel-default top-padding">
        <div class="panel-body">
            <strong>{{ lang._('Selected routers') }}</strong>
            <span class="text-muted">{{ lang._('Choose an action to run on the currently selected rows.') }}</span>
            <div class="top-padding">
                <button class="btn btn-primary" id="bulkSyncRoutersBtn" type="button" disabled="disabled" title="{{ lang._('Pull current configs, compare them with configured parent routers, push parent configs where needed, and reload affected services.') }}">
                    <span class="fa fa-random fa-fw"></span> {{ lang._('Sync Configs') }}
                </button>
                <button class="btn btn-info" id="bulkSysUpdateBtn" type="button" disabled="disabled" title="{{ lang._('Run apk update and apk upgrade on the selected routers.') }}">
                    <span class="fa fa-download fa-fw"></span> {{ lang._('Sys Update') }}
                </button>
                <button class="btn btn-warning" id="bulkRebootRoutersBtn" type="button" disabled="disabled" title="{{ lang._('Reboot the selected routers.') }}">
                    <span class="fa fa-refresh fa-fw"></span> {{ lang._('Reboot') }}
                </button>
                <button class="btn btn-success" id="bulkRadiosOnBtn" type="button" disabled="disabled" title="{{ lang._('Enable Wi-Fi radios on the selected routers.') }}">
                    {{ lang._('Radios On') }}
                </button>
                <button class="btn btn-warning" id="bulkRadiosOffBtn" type="button" disabled="disabled" title="{{ lang._('Disable Wi-Fi radios on the selected routers.') }}">
                    {{ lang._('Radios Off') }}
                </button>
                <button class="btn btn-info" id="bulkRoamingBaselineBtn" type="button" disabled="disabled" title="{{ lang._('Install usteer if needed and apply the standard roaming baseline: auto channels, 802.11r/k, BSS transition, and steering settings.') }}">
                    <span class="fa fa-exchange fa-fw"></span> {{ lang._('Apply Roaming Baseline') }}
                </button>
            </div>
        </div>
    </div>
</div>

{{ partial("layout_partials/base_dialog", ['fields': formDialogRouter, 'id': formGridRouter['edit_dialog_id'], 'label': lang._('Edit router')]) }}

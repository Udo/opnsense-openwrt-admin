<script>
    $(document).ready(function() {
        const editDialogId = "#{{ formGridRouter['edit_dialog_id'] }}";
        const gridId = "#{{ formGridRouter['table_id'] }}";
        const sshKeyFieldId = "router\\.ssh_key_ref";
        const configSyncFields = [
            {type: "wifi", fieldId: "router\\.sync_wifi_config_from", restoreLabel: "{{ lang._('Restore wifi backup') }}"},
            {type: "system", fieldId: "router\\.sync_system_config_from", restoreLabel: "{{ lang._('Restore system backup') }}"},
            {type: "firewall", fieldId: "router\\.sync_firewall_config_from", restoreLabel: "{{ lang._('Restore firewall backup') }}"},
            {type: "dhcp", fieldId: "router\\.sync_dhcp_config_from", restoreLabel: "{{ lang._('Restore dhcp backup') }}"},
            {type: "rpcd", fieldId: "router\\.sync_rpcd_config_from", restoreLabel: "{{ lang._('Restore rpcd backup') }}"}
        ];
        const routerAddressFieldId = "router\\.address";
        const routerStatusFieldId = "router\\.status";
        const routerVersionFieldId = "router\\.version";
        const routerHardwareFieldId = "router\\.hardware";
        const routerSyncStatusFieldId = "router\\.sync_status";
        const brokerBannerId = "#openwrtAdminBrokerBanner";
        const bulkActionStatusId = "#openwrtAdminBulkActionStatus";
        const bulkActionStatusClasses = "alert alert-danger alert-info alert-success hidden";
        const bulkActionButtonIds = "#bulkRebootRoutersBtn, #bulkRadiosOnBtn, #bulkRadiosOffBtn, #bulkSyncRoutersBtn";
        let currentEditRouterUuid = null;
        let runtimeRouters = [];

        function copyTextToClipboard(text) {
            if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
                return navigator.clipboard.writeText(text);
            }

            const deferred = $.Deferred();
            const temp = $("<textarea>")
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

        function updateCopyButtonState() {
            const hasValue = $("#" + sshKeyFieldId).val() !== "";
            $("#copySshPublicKeyBtn").prop("disabled", !hasValue);
            $("#openRouterSshKeysPageBtn").prop("disabled", $("#" + routerAddressFieldId).val() === "");
        }

        function ensureCopyButton() {
            const target = $("#select_" + sshKeyFieldId);
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
                const target = $("#select_" + config.fieldId);
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
            const address = $("#" + routerAddressFieldId).val();
            let current = null;
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

            const current = currentRuntimeRouter();
            if (current && current.router_uuid) {
                currentEditRouterUuid = current.router_uuid;
                return currentEditRouterUuid;
            }

            return null;
        }

        function updateSyncSourceOptions() {
            configSyncFields.forEach(function(config) {
                const select = $("#" + config.fieldId);
                if (!select.length) {
                    return;
                }

                if (!select.data("all-options")) {
                    const allOptions = [];
                    select.find("option").each(function() {
                        allOptions.push({
                            value: $(this).attr("value") || "",
                            label: $(this).text()
                        });
                    });
                    select.data("all-options", allOptions);
                }

                const current = currentRuntimeRouter();
                const currentModel = current && current.hardware_model ? current.hardware_model : "";
                const selectedValue = select.val() || "";
                const runtimeByUuid = {};
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

                    const editingUuid = effectiveEditRouterUuid();
                    if (editingUuid && option.value === editingUuid) {
                        return;
                    }

                    const candidate = runtimeByUuid[option.value] || null;
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

        function loadRestoreBackups(configType) {
            const backupSelect = $("#openwrtAdminRestoreBackupSelect_" + configType);
            const backupStatus = $("#openwrtAdminRestoreBackupStatus_" + configType);
            const restoreButton = $("#restore" + configType + "BackupBtn");

            if (!backupSelect.length) {
                return;
            }

            const routerUuid = effectiveEditRouterUuid();
            if (!routerUuid) {
                backupSelect.empty().append($("<option>").text("{{ lang._('Save the router first to enable restore.') }}"));
                restoreButton.prop("disabled", true);
                backupStatus.text("");
                return;
            }

            backupStatus.text("{{ lang._('Loading backups...') }}");
            ajaxCall("/api/openwrtadmin/service/config_backups/", {router_uuid: routerUuid, config_type: configType}, function(data) {
                backupSelect.empty();
                const backups = Array.isArray(data.backups) ? data.backups : [];
                if (!backups.length) {
                    backupSelect.append($("<option>").text("{{ lang._('No backups stored yet.') }}").attr("value", ""));
                    restoreButton.prop("disabled", true);
                    backupStatus.text("");
                    return;
                }

                backups.forEach(function(item) {
                    const label = (item.last_seen_at || item.created_at || "") +
                        " | " + (item.content_hash || "").slice(0, 12) +
                        " | " + (item.size_bytes || 0) + " B";
                    backupSelect.append($("<option>").attr("value", item.content_hash).text(label));
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

        function updateBrokerBanner() {
            ajaxCall("/api/openwrtadmin/service/status/", {}, function(data) {
                const broker = data.broker || null;
                if (broker && broker.ok && broker.body) {
                    $(brokerBannerId).addClass("hidden").text("");
                    return;
                }

                const serviceState = data.service || "unknown";
                $(brokerBannerId)
                    .removeClass("hidden")
                    .text("PHP cannot reach the OpenWrt Admin broker on 127.0.0.1:9783. Service status: " + serviceState + ".");
            });
        }

        function selectedRouterIds() {
            return $(gridId).bootgrid("getSelectedRows") || [];
        }

        function routerRowData(rowId) {
            const bootgrid = $(gridId).data("UIBootgrid");
            if (bootgrid && bootgrid.table) {
                const row = bootgrid.table.getRow(rowId);
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
            const node = $(bulkActionStatusId);
            node.removeClass(bulkActionStatusClasses);
            if (!message) {
                node.addClass("hidden").text("");
                return;
            }

            const cssClass = level === "success"
                ? "alert alert-info"
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
            const routers = selectedRouterIds();
            if (!routers.length) {
                setBulkActionStatus("Select at least one router.", "error");
                updateBulkActionButtons();
                return;
            }

            stdDialogConfirm(title, prompt, "{{ lang._('Yes') }}", "{{ lang._('Cancel') }}", function() {
                setBulkActionStatus("Running " + title.toLowerCase() + "...", "info");
                $(bulkActionButtonIds).prop("disabled", true);
                ajaxCall("/api/openwrtadmin/service/bulk_action/", {action: action, routers: routers}, function(data) {
                    const failed = Array.isArray(data.results)
                        ? data.results.filter(function(item) { return !item.ok; })
                        : [];

                    if ((data.status || "") !== "ok") {
                        setBulkActionStatus(data.message || "Bulk action failed.", "error");
                    } else if (failed.length) {
                        const details = failed.map(function(item) {
                            return (item.address || item.router_uuid || "router") + ": " + (item.message || "error");
                        }).join("; ");
                        setBulkActionStatus((data.successful || 0) + " ok, " + failed.length + " failed. " + details, "error");
                    } else if (action === "sync_configs") {
                        setBulkActionStatus((data.changed || 0) + " router(s) synced.", "success");
                    } else {
                        setBulkActionStatus((data.successful || 0) + " router(s) updated.", "success");
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
                        const rowId = $(event.currentTarget).data("row-id");
                        const row = routerRowData(rowId);
                        const address = row && row.address ? row.address : "";
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
                        const value = row.sync_status || "";
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

        updateBrokerBanner();
        updateBulkActionIcons();
        updateBulkActionButtons();
        loadRuntimeRouters();

        window.setInterval(function() {
            updateBrokerBanner();
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
            const ref = $("#" + sshKeyFieldId).val();
            if (!ref) {
                $("#copySshPublicKeyStatus").text("No key selected.");
                updateCopyButtonState();
                return;
            }

            ajaxCall("/api/openwrtadmin/settings/get_ssh_public_key/", {ref: ref}, function(data) {
                if (data.status !== "ok" || !data.public_key) {
                    $("#copySshPublicKeyStatus").text("Unable to load key.");
                    return;
                }

                copyTextToClipboard(data.public_key).then(function() {
                    $("#copySshPublicKeyStatus").text("Copied.");
                }).catch(function() {
                    $("#copySshPublicKeyStatus").text("Clipboard access failed.");
                });
            });
        });

        $(document).on("click", "#openRouterSshKeysPageBtn", function() {
            const address = $("#" + routerAddressFieldId).val();
            if (!address) {
                $("#copySshPublicKeyStatus").text("No router address set.");
                updateCopyButtonState();
                return;
            }

            const url = "http://" + address + "/cgi-bin/luci/admin/system/admin/sshkeys";
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

        $(document).on("click", "#bulkSyncRoutersBtn", function() {
            performBulkAction("sync_configs", "{{ lang._('Sync configs') }}", "{{ lang._('Sync configs on the selected routers where needed?') }}");
        });

        $(document).on("click", ".openwrtAdminRestoreBackupBtn", function() {
            const configType = $(this).data("config-type");
            const contentHash = $("#openwrtAdminRestoreBackupSelect_" + configType).val();
            const statusSelector = "#openwrtAdminRestoreBackupStatus_" + configType;
            const prettyType = configType === "wifi" ? "Wi-Fi" : configType;
            const routerUuid = effectiveEditRouterUuid();
            if (!routerUuid || !contentHash) {
                $(statusSelector).text("{{ lang._('No backup selected.') }}");
                return;
            }

            stdDialogConfirm(
                "Restore " + prettyType + " backup",
                "Restore the selected " + prettyType + " backup to this router?",
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
    <div class="alert alert-danger hidden" id="openwrtAdminBrokerBanner"></div>
    <div class="hidden" id="openwrtAdminBulkActionStatus"></div>
    {{ partial('layout_partials/base_bootgrid_table', formGridRouter + {
        'command_width': '135',
        'grid_commands': {
            'bulkRebootRoutersBtn': {
                'class': 'btn btn-xs btn-default',
                'icon_class': 'fa fa-fw fa-refresh',
                'title': lang._('Reboot selected routers'),
                'data': {
                    'toggle': 'tooltip'
                }
            },
            'bulkRadiosOnBtn': {
                'class': 'btn btn-xs btn-default',
                'icon_class': 'fa fa-fw',
                'title': lang._('Enable radios on selected routers'),
                'data': {
                    'toggle': 'tooltip'
                }
            },
            'bulkRadiosOffBtn': {
                'class': 'btn btn-xs btn-default',
                'icon_class': 'fa fa-fw',
                'title': lang._('Disable radios on selected routers'),
                'data': {
                    'toggle': 'tooltip'
                }
            },
            'bulkSyncRoutersBtn': {
                'class': 'btn btn-xs btn-default',
                'icon_class': 'fa fa-fw fa-exchange',
                'title': lang._('Sync selected routers from their configured config sources'),
                'data': {
                    'toggle': 'tooltip'
                }
            }
        }
    }) }}
</div>

{{ partial("layout_partials/base_dialog", ['fields': formDialogRouter, 'id': formGridRouter['edit_dialog_id'], 'label': lang._('Edit router')]) }}

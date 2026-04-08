<script>
    $(document).ready(function() {
        const editDialogId = "#{{ formGridRouter['edit_dialog_id'] }}";
        const gridId = "#{{ formGridRouter['table_id'] }}";
        const sshKeyFieldId = "router\\.ssh_key_ref";
        const routerAddressFieldId = "router\\.address";
        const routerStatusFieldId = "router\\.status";
        const routerVersionFieldId = "router\\.version";
        const brokerBannerId = "#openwrtAdminBrokerBanner";

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

        function hideLiveStatusFields() {
            $("#" + routerStatusFieldId).closest(".form-group, tr").hide();
            $("#" + routerVersionFieldId).closest(".form-group, tr").hide();
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

        $(gridId).UIBootgrid({
            search: "/api/openwrtadmin/settings/search_router/",
            get: "/api/openwrtadmin/settings/get_router/",
            set: "/api/openwrtadmin/settings/set_router/",
            add: "/api/openwrtadmin/settings/add_router/",
            del: "/api/openwrtadmin/settings/del_router/"
        });

        updateBrokerBanner();

        window.setInterval(function() {
            updateBrokerBanner();
            if (!$(editDialogId).is(":visible")) {
                $(gridId).bootgrid("reload");
            }
        }, 60000);

        $(document).on("shown.bs.modal", editDialogId, function() {
            ensureCopyButton();
            hideLiveStatusFields();
            $("#" + sshKeyFieldId).selectpicker("refresh");
            updateCopyButtonState();
        });

        $(document).on("change", "#" + sshKeyFieldId, function() {
            $("#copySshPublicKeyStatus").text("");
            updateCopyButtonState();
        });

        $(document).on("input change", "#" + routerAddressFieldId, function() {
            updateCopyButtonState();
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
    });
</script>

<div class="content-box">
    <div class="alert alert-danger hidden" id="openwrtAdminBrokerBanner"></div>
    {{ partial('layout_partials/base_bootgrid_table', formGridRouter) }}
</div>

{{ partial("layout_partials/base_dialog", ['fields': formDialogRouter, 'id': formGridRouter['edit_dialog_id'], 'label': lang._('Edit router')]) }}

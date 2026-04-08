<script>
    $(document).ready(function() {
        const editDialogId = "#{{ formGridRouter['edit_dialog_id'] }}";
        const sshKeyFieldId = "router\\.ssh_key_ref";

        function updateCopyButtonState() {
            const hasValue = $("#" + sshKeyFieldId).val() !== "";
            $("#copySshPublicKeyBtn").prop("disabled", !hasValue);
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
                    '<span id="copySshPublicKeyStatus" class="text-muted"></span>' +
                '</div>'
            );
            updateCopyButtonState();
        }

        $("#{{ formGridRouter['table_id'] }}").UIBootgrid({
            search: "/api/openwrtadmin/settings/search_router/",
            get: "/api/openwrtadmin/settings/get_router/",
            set: "/api/openwrtadmin/settings/set_router/",
            add: "/api/openwrtadmin/settings/add_router/",
            del: "/api/openwrtadmin/settings/del_router/"
        });

        $(document).on("shown.bs.modal", editDialogId, function() {
            ensureCopyButton();
            $("#" + sshKeyFieldId).selectpicker("refresh");
            updateCopyButtonState();
        });

        $(document).on("change", "#" + sshKeyFieldId, function() {
            $("#copySshPublicKeyStatus").text("");
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

                navigator.clipboard.writeText(data.public_key).then(function() {
                    $("#copySshPublicKeyStatus").text("Copied.");
                }).catch(function() {
                    $("#copySshPublicKeyStatus").text("Clipboard access failed.");
                });
            });
        });
    });
</script>

<div class="content-box">
    {{ partial('layout_partials/base_bootgrid_table', formGridRouter) }}
</div>

{{ partial("layout_partials/base_dialog", ['fields': formDialogRouter, 'id': formGridRouter['edit_dialog_id'], 'label': lang._('Edit router')]) }}

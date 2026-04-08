<script>
    $(document).ready(function() {
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

        function refreshSettings() {
            return mapDataToFormUI({'frmGeneralSettings': '/api/openwrtadmin/general/get'}).done(function() {
                $("#settings\\.managed_public_key").attr("readonly", "readonly");
                $("#settings\\.managed_private_key").attr("readonly", "readonly");
            });
        }

        refreshSettings();

        $("#saveSettingsAct").click(function() {
            saveFormToEndpoint('/api/openwrtadmin/general/set', 'frmGeneralSettings');
        });

        $("#generateManagedKeyAct").click(function() {
            saveFormToEndpoint('/api/openwrtadmin/general/set', 'frmGeneralSettings', function() {
                ajaxCall('/api/openwrtadmin/general/generate_managed_keypair/', {
                    settings: {
                        managed_key_comment: $("#settings\\.managed_key_comment").val()
                    }
                }, function(data) {
                    if (data.result === 'saved') {
                        refreshSettings();
                    }
                });
            }, true);
        });

        $("#copyManagedPublicKeyAct").click(function() {
            const publicKey = $("#settings\\.managed_public_key").val();
            if (!publicKey) {
                $("#managedKeyCopyStatus").text("No managed public key available.");
                return;
            }

            copyTextToClipboard(publicKey).then(function() {
                $("#managedKeyCopyStatus").text("Copied.");
            }).catch(function() {
                $("#managedKeyCopyStatus").text("Clipboard access failed.");
            });
        });
    });
</script>

<div class="content-box">
    {{ partial("layout_partials/base_form",['fields':generalForm,'id':'frmGeneralSettings'])}}
    <div class="col-md-12">
        <hr />
        <button class="btn btn-primary" id="saveSettingsAct" type="button"><b>{{ lang._('Save') }}</b></button>
        <button class="btn btn-default" id="generateManagedKeyAct" type="button"><b>{{ lang._('Generate SSH Keypair') }}</b></button>
        <button class="btn btn-default" id="copyManagedPublicKeyAct" type="button"><b>{{ lang._('Copy Public Key') }}</b></button>
        <span id="managedKeyCopyStatus" class="text-muted"></span>
    </div>
</div>

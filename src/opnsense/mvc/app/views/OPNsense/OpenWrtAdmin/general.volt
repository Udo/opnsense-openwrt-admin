{{ partial("OPNsense/OpenWrtAdmin/_js_utils") }}

<script>
    $(document).ready(function() {
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
            var publicKey = $("#settings\\.managed_public_key").val();
            if (!publicKey) {
                $("#managedKeyCopyStatus").text("{{ lang._('No managed public key available.') }}");
                return;
            }

            openwrtAdminCopyToClipboard(publicKey).then(function() {
                $("#managedKeyCopyStatus").text("{{ lang._('Copied.') }}");
            }).catch(function() {
                $("#managedKeyCopyStatus").text("{{ lang._('Clipboard access failed.') }}");
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

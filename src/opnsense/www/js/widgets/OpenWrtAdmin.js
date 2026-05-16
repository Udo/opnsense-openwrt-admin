/*
 * OpenWrt Admin dashboard widget.
 * Displays a live fleet summary table of all managed OpenWrt routers,
 * mirroring the data shown in Services → OpenWrt Admin → Dashboard.
 *
 * Calls /api/openwrtadmin/service/routers/ and
 * /api/openwrtadmin/service/status/ (same endpoints as the plugin page).
 *
 * Extends BaseTableWidget so that column layout, responsive sizing, and
 * font scaling are handled consistently with other OPNsense dashboard
 * widgets (e.g. Gateways.js).
 */
export default class OpenWrtAdmin extends BaseTableWidget {

    static get COLUMNS() {
        return [
            { id: 'address',      labelKey: 'address',     label: 'Address'  },
            { id: 'hostname',     labelKey: 'hostname',    label: 'Hostname' },
            { id: 'status',       labelKey: 'status',      label: 'Status'   },
            { id: 'load',         labelKey: 'load',        label: 'Load'     },
            { id: 'uptime',       labelKey: 'uptime',      label: 'Uptime'   },
            { id: 'memory',       labelKey: 'memory',      label: 'Memory'   },
            { id: 'wifi_clients', labelKey: 'wifi_clients', label: 'WiFi'    },
            { id: 'channels',     labelKey: 'channels',    label: 'Channels' },
            { id: 'bandwidth',    labelKey: 'bandwidth',   label: 'Bandwidth'},
            { id: 'signal',       labelKey: 'signal',      label: 'Signal'   },
        ];
    }

    constructor(config) {
        super(config);
        this.title = 'OpenWrt Admin';
        this.configurable = true;
        this._refreshing = false;
        this._activeColumns = OpenWrtAdmin.COLUMNS.map(c => c.id);
        this._lastRouters = [];
    }

    getGridOptions() {
        return { sizeToContent: 500 };
    }

    // -------------------------------------------------------------------------
    // Column options
    // -------------------------------------------------------------------------

    async getWidgetOptions() {
        return {
            columns: {
                title: this.translations.columns ?? 'Columns',
                type: 'select_multiple',
                options: OpenWrtAdmin.COLUMNS.map(col => ({
                    value: col.id,
                    label: this.translations[col.labelKey] ?? col.label,
                })),
                default: OpenWrtAdmin.COLUMNS.map(c => c.id),
            },
        };
    }

    async onWidgetOptionsChanged(options) {
        this._activeColumns = options.columns?.length
            ? options.columns
            : OpenWrtAdmin.COLUMNS.map(c => c.id);
        this._buildTable();
        this._renderRows(this._lastRouters);
    }

    // -------------------------------------------------------------------------
    // Markup
    // -------------------------------------------------------------------------

    getMarkup() {
        // getMarkup() is called after setId(), so this.id is available.
        return $(`
            <div id="openwrtadmin_${this.id}">
                <div id="openwrtadmin_banner_${this.id}"
                     class="alert alert-warning"
                     style="display:none; margin-bottom:6px; padding:6px 10px;">
                </div>
                <div id="openwrtadmin_wrapper_${this.id}" style="overflow-x:auto;"></div>
            </div>
        `);
    }

    async onMarkupRendered() {
        const config = await this.getWidgetConfig();
        if (config?.columns?.length) {
            this._activeColumns = config.columns;
        }
        this._buildTable();
        await this._refresh();
    }

    async onWidgetTick() {
        if (this._refreshing) return;
        await this._refresh();
    }

    onWidgetResize(elem, width, height) {
        // Let BaseTableWidget apply its sizeStates for flextable elements.
        const handled = super.onWidgetResize(elem, width, height);

        // Scale grid-item font at widget-level breakpoints so headers and
        // data cells always change together (fixes the font-size mismatch on
        // resize that a hardcoded table style cannot handle).
        const $grid = $(`#openwrtadmin_wrapper_${this.id} .grid-table`);
        if (width < 600) {
            $grid.find('.grid-item').css('font-size', '11px');
        } else if (width < 900) {
            $grid.find('.grid-item').css('font-size', '12px');
        } else {
            $grid.find('.grid-item').css('font-size', '');
        }

        return handled;
    }

    // -------------------------------------------------------------------------
    // Table construction
    // -------------------------------------------------------------------------

    _buildTable() {
        // Clean up previous table registration so createTable starts fresh.
        delete this.tables['openwrtadmin_table'];

        const activeColDefs = OpenWrtAdmin.COLUMNS.filter(c => this._activeColumns.includes(c.id));
        const headers = activeColDefs.map(c => this.translations[c.labelKey] ?? c.label);

        const $table = this.createTable('openwrtadmin_table', {
            headerPosition: 'top',
            headers,
        });

        $(`#openwrtadmin_wrapper_${this.id}`).empty().append($table);
    }

    // -------------------------------------------------------------------------
    // Data refresh
    // -------------------------------------------------------------------------

    async _refresh() {
        this._refreshing = true;
        try {
            await Promise.all([
                this._updateBrokerBanner(),
                this._updateRouterTable(),
            ]);
        } finally {
            this._refreshing = false;
        }
    }

    async _updateBrokerBanner() {
        let data;
        try {
            data = await this.ajaxCall('/api/openwrtadmin/service/status/');
        } catch (e) {
            return;
        }
        const $banner = $(`#openwrtadmin_banner_${this.id}`);
        const broker = data.broker ?? null;
        if (broker && broker.ok && broker.body) {
            $banner.hide().text('');
        } else {
            const svc = data.service ?? 'unknown';
            $banner.text(
                (this.translations.broker_down ?? 'The OpenWrt Admin background service is not running') +
                ` (${svc}). ` +
                (this.translations.broker_down_hint ?? 'Go to Services → OpenWrt Admin to start it.')
            ).show();
        }
    }

    async _updateRouterTable() {
        let data;
        try {
            data = await this.ajaxCall('/api/openwrtadmin/service/routers/');
        } catch (e) {
            return;
        }
        const routers = Array.isArray(data.routers) ? data.routers : [];
        if (!this.dataChanged('routers', routers)) return;

        this._lastRouters = routers;
        this._renderRows(routers);
    }

    _renderRows(routers) {
        // Remove any leftover grid rows (handles the empty→data transition).
        $(`#openwrtadmin_table .grid-row`).remove();

        if (!routers.length) {
            // Span the full grid width with a single centred message.
            $(`#openwrtadmin_table`).append(`
                <div class="grid-row">
                    <div class="grid-item"
                         style="grid-column:1/-1;text-align:center;color:#888;padding:8px 0;">
                        ${this._esc(this.translations.no_routers ?? 'No routers registered yet.')}
                    </div>
                </div>
            `);
            return;
        }

        const rows = routers.map(router =>
            this._activeColumns.map(colId => this._cellHtml(colId, router))
        );
        this.updateTable('openwrtadmin_table', rows);
    }

    // -------------------------------------------------------------------------
    // Cell renderers — return HTML strings as required by BaseTableWidget
    // -------------------------------------------------------------------------

    _cellHtml(colId, router) {
        switch (colId) {
            case 'address':
                return this._esc(router.address ?? '');

            case 'hostname': {
                const host = this._esc(router.detected_hostname ?? router.configured_hostname ?? '');
                const desc = (router.description ?? '').trim();
                return host + (desc ? `<div class="small text-muted">${this._esc(desc)}</div>` : '');
            }

            case 'status': {
                let text = router.status_text ?? 'Unknown';
                let cls  = 'label-danger';
                if (router.reachable) {
                    if      (text.startsWith('Healthy'))  { text = 'ok';       cls = 'label-success'; }
                    else if (text.startsWith('Warning'))  { text = 'warning';  cls = 'label-warning'; }
                    else if (text.startsWith('Critical')) { text = 'critical'; cls = 'label-danger';  }
                    else                                  {                    cls = 'label-success'; }
                }
                return `<span class="label ${cls}">${this._esc(text)}</span>`;
            }

            case 'load':
                return this._esc(this._formatLoad(router.load_1m));

            case 'uptime':
                return this._esc(this._formatUptime(router.uptime_seconds));

            case 'memory':
                return this._esc(this._formatPercent(router.memory_used_pct));

            case 'wifi_clients':
                return this._wifiHtml(router);

            case 'channels':
                return this._channelsHtml(router);

            case 'bandwidth':
                return this._esc(
                    'rx ' + this._formatRate(router.rx_bps) +
                    ' / tx ' + this._formatRate(router.tx_bps)
                );

            case 'signal':
                return this._signalHtml(router);

            default:
                return '';
        }
    }

    _wifiHtml(router) {
        if (!router.wifi_clients_by_network) {
            return router.wifi_clients == null
                ? '<span class="text-muted">n/a</span>'
                : this._esc(String(router.wifi_clients));
        }

        let byNetwork = router.wifi_clients_by_network;
        if (typeof byNetwork === 'string') {
            try { byNetwork = JSON.parse(byNetwork); } catch (e) { byNetwork = null; }
        }

        if (!byNetwork || typeof byNetwork !== 'object') {
            return '<span class="text-muted">n/a</span>';
        }

        const networks = Object.keys(byNetwork).sort();
        if (!networks.length) return '<span class="text-muted">n/a</span>';

        return networks.map(net =>
            `<div class="small">` +
            `<span class="text-muted">${this._esc(net)}: </span>` +
            `<strong>${this._esc(String(byNetwork[net]))}</strong>` +
            `</div>`
        ).join('');
    }

    _channelsHtml(router) {
        let values = router.radio_channels;
        if (typeof values === 'string') {
            try { values = JSON.parse(values); } catch (e) { values = null; }
        }
        if (!Array.isArray(values) || !values.length) {
            return '<span class="text-muted">n/a</span>';
        }
        return values.map(v => `<div class="small">${this._esc(String(v))}</div>`).join('');
    }

    _signalHtml(router) {
        const placeholder =
            '<div class="small text-muted">---</div>' +
            '<div style="width:120px;height:10px;border-radius:999px;background:#d1d5db;margin-top:4px;"></div>';

        let hist = router.signal_histogram;
        if (typeof hist === 'string') {
            try { hist = JSON.parse(hist); } catch (e) { hist = null; }
        }
        if (!hist) return placeholder;

        const BUCKETS = [
            { key: 'excellent', color: '#22c55e' },
            { key: 'good',      color: '#84cc16' },
            { key: 'fair',      color: '#f59e0b' },
            { key: 'weak',      color: '#ef4444' },
        ];
        const total = BUCKETS.reduce((s, b) => s + (hist[b.key] ?? 0), 0);
        if (!total) return placeholder;

        const label =
            `<div class="small text-muted">` +
            `best ${this._esc(String(router.best_signal_dbm))} / ` +
            `worst ${this._esc(String(router.worst_signal_dbm))} dBm` +
            `</div>`;

        const segments = BUCKETS
            .filter(b => (hist[b.key] ?? 0) > 0)
            .map(b => {
                const pct = ((hist[b.key] / total) * 100).toFixed(1);
                return `<span style="display:block;width:${pct}%;background:${b.color};"` +
                       ` title="${b.key}: ${hist[b.key]}"></span>`;
            })
            .join('');

        const bar =
            `<div style="display:flex;width:120px;height:10px;border-radius:999px;` +
            `overflow:hidden;background:#e5e7eb;margin-top:4px;">` +
            segments + `</div>`;

        return label + bar;
    }

    // -------------------------------------------------------------------------
    // Formatting helpers (mirrors _js_utils.volt)
    // -------------------------------------------------------------------------

    _formatLoad(value) {
        return value == null ? 'n/a' : Number(value).toFixed(2);
    }

    _formatPercent(value) {
        return value == null ? 'n/a' : value + '%';
    }

    _formatUptime(seconds) {
        if (seconds == null) return 'n/a';
        const total   = Math.max(0, parseInt(seconds, 10) || 0);
        const days    = Math.floor(total / 86400);
        const hours   = Math.floor((total % 86400) / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const parts   = [];
        if (days  > 0)             parts.push(days  + 'd');
        if (hours > 0 || days > 0) parts.push(hours + 'h');
        parts.push(minutes + 'm');
        return parts.join(' ');
    }

    _formatRate(value) {
        if (value == null || value === '') return 'n/a';
        const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
        let amount  = Number(value);
        let unit    = 0;
        while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit++; }
        const dec = (amount >= 100 || unit === 0) ? 0 : 1;
        return amount.toFixed(dec) + ' ' + units[unit];
    }

    // Minimal HTML escaping for user-supplied strings inserted via innerHTML.
    _esc(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}

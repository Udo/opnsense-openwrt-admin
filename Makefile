PLUGIN_NAME=		openwrt-admin
PLUGIN_VERSION=		0.1
PLUGIN_COMMENT=		OpenWrt fleet administration UI
PLUGIN_MAINTAINER=	udo@undenheim.kautschuk.com

test:
	python3 -m unittest discover -s tests -p 'test_*.py'

.include "../../Mk/plugins.mk"

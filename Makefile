PLUGIN_NAME=		openwrt-admin
PLUGIN_VERSION=		0.1
PLUGIN_REVISION=	1
PLUGIN_COMMENT=		OpenWrt fleet administration UI
PLUGIN_LICENSE=		BSD2CLAUSE
PLUGIN_MAINTAINER=	udo@kautschuk.com
PLUGIN_WWW=		https://github.com/Udo/opnsense-openwrt-admin

test:
	python3 -m unittest discover -s tests -p 'test_*.py'

.include "../../Mk/plugins.mk"

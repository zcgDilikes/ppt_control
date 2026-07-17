<script>
import { updateSendRecordsTabBarBadge } from './common/uploadRoomFile.js';

export default {
	globalData: {
		pptSocket: null,
		/** 与首页 tabbar-1 同步：PC 接收端是否在同房间就绪 */
		peerPcOnline: false
	},
	onLaunch: function() {
		console.log('App Launch');

		setTimeout(() => {
			updateSendRecordsTabBarBadge();
		}, 1000);
	},
	onShow: function() {
		console.log('App Show');
		updateSendRecordsTabBarBadge();
	},
	onHide: function() {
		console.log('App Hide');
	}
};
</script>

<style>
/*每个页面公共css */ 
</style>

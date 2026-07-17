<template>
	<view class="page">
		<view class="card hero">
			<text class="logo">📽</text>
			<text class="name">{{ appName }}</text>
			<text class="ver">版本 {{ version }}</text>
		</view>
		<view class="card">
			<text class="body">
				PPT 遥控小程序用于通过手机连接房间，遥控电脑端放映与文件传输。请在遵守当地法律法规与平台规则的前提下使用。
			</text>
		</view>
	</view>
</template>

<script>
import { APP_NAME, APP_VERSION } from '../../common/meContent.js';

export default {
	data() {
		return {
			appName: APP_NAME,
			version: APP_VERSION
		};
	}
};
</script>

<style scoped>
.page {
	min-height: 100vh;
	padding: 24rpx;
	padding-bottom: 48rpx;
	background: #f0f0f0;
	box-sizing: border-box;
}

.card {
	background: #fff;
	border-radius: 16rpx;
	padding: 32rpx 28rpx;
	margin-bottom: 24rpx;
	box-shadow: 0 4rpx 24rpx rgba(0, 0, 0, 0.06);
	box-sizing: border-box;
}

.hero {
	display: flex;
	flex-direction: column;
	align-items: center;
	text-align: center;
	padding: 48rpx 28rpx 40rpx;
}

.logo {
	font-size: 96rpx;
	line-height: 1;
	margin-bottom: 20rpx;
}

.name {
	font-size: 36rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 12rpx;
}

.ver {
	font-size: 26rpx;
	color: #888;
}

.body {
	font-size: 26rpx;
	color: #555;
	line-height: 1.65;
}
</style>

<template>
	<view class="page">
		<view class="card">
			<text class="body">{{ text }}</text>
		</view>
	</view>
</template>

<script>
import { AGREEMENT_PLACEHOLDER } from '../../common/meContent.js';

export default {
	data() {
		return {
			text: AGREEMENT_PLACEHOLDER
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
	box-shadow: 0 4rpx 24rpx rgba(0, 0, 0, 0.06);
	box-sizing: border-box;
}

.body {
	font-size: 26rpx;
	color: #444;
	line-height: 1.75;
	white-space: pre-wrap;
}
</style>

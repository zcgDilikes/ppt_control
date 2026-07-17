<template>
	<view class="page">
		<view class="card intro">
			<text class="intro-text">以下为功能说明占位，可按实际产品修改文案。</text>
		</view>
		<view v-for="(s, i) in sections" :key="i" class="card block">
			<text class="block-title">{{ s.title }}</text>
			<text class="block-body">{{ s.body }}</text>
		</view>
	</view>
</template>

<script>
import { MANUAL_SECTIONS } from '../../common/meContent.js';

export default {
	data() {
		return {
			sections: MANUAL_SECTIONS
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
	padding: 28rpx;
	margin-bottom: 24rpx;
	box-shadow: 0 4rpx 24rpx rgba(0, 0, 0, 0.06);
	box-sizing: border-box;
}

.intro {
	padding: 24rpx 28rpx;
}

.intro-text {
	font-size: 26rpx;
	color: #888;
	line-height: 1.5;
}

.block-title {
	display: block;
	font-size: 30rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 16rpx;
}

.block-body {
	display: block;
	font-size: 26rpx;
	color: #555;
	line-height: 1.65;
	white-space: pre-wrap;
}
</style>

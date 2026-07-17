<template>
	<view class="page">
		<text class="title">发图文</text>
		<text class="hint">将图片上传到当前已连接的房间（与首页房间号一致）</text>
		<button class="btn" type="primary" @click="pickAndUpload">选择图片并上传</button>
	</view>
</template>

<script>
import { getUploadContext, uploadRoomFile } from '../../../common/uploadRoomFile.js';

export default {
	methods: {
		pickAndUpload() {
			const ctx = getUploadContext();
			if (!ctx.ok) {
				uni.showToast({ title: ctx.message, icon: 'none' });
				return;
			}
			uni.chooseImage({
				count: 1,
				sizeType: ['compressed', 'original'],
				sourceType: ['album', 'camera'],
				success: (res) => {
					const path = res.tempFilePaths && res.tempFilePaths[0];
					if (!path) return;
					const base = path.split(/[/\\]/).pop() || '';
					uploadRoomFile(path, { type: 'image', displayName: base }).catch(() => {});
				},
				fail: (err) => {
					const msg = (err && err.errMsg) || '';
					if (/cancel|取消/i.test(msg)) return;
					uni.showToast({ title: '选择图片失败', icon: 'none' });
				}
			});
		}
	}
};
</script>

<style scoped>
.page {
	padding: 40rpx;
	min-height: 60vh;
}
.title {
	display: block;
	font-size: 36rpx;
	font-weight: 600;
	margin-bottom: 24rpx;
}
.hint {
	display: block;
	font-size: 26rpx;
	color: #666;
	line-height: 1.5;
	margin-bottom: 48rpx;
}
.btn {
	width: 100%;
}
</style>

<template>
	<view class="page">
		<text class="title">发视频</text>
		<text class="hint">将视频上传到当前已连接的房间（与首页房间号一致）</text>
		<button class="btn" type="primary" @click="pickAndUpload">选择视频并上传</button>
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
			uni.chooseVideo({
				sourceType: ['album', 'camera'],
				compressed: true,
				success: (res) => {
					const path = res.tempFilePath;
					if (!path) return;
					const name = (res.name && String(res.name).trim()) || '';
					uploadRoomFile(path, { type: 'video', displayName: name }).catch(() => {});
				},
				fail: (err) => {
					const msg = (err && err.errMsg) || '';
					if (/cancel|取消/i.test(msg)) return;
					uni.showToast({ title: '选择视频失败', icon: 'none' });
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

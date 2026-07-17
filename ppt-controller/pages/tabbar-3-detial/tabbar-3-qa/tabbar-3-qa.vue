<template>
	<view class="page">
		<text class="title">发文件</text>
		<text class="hint">从微信会话中选择文件上传到当前已连接的房间</text>
		<!-- #ifdef MP-WEIXIN -->
		<button class="btn" type="primary" @click="pickAndUpload">选择聊天文件并上传</button>
		<!-- #endif -->
		<!-- #ifndef MP-WEIXIN -->
		<text class="warn">请在微信小程序中使用「发文件」</text>
		<!-- #endif -->
	</view>
</template>

<script>
import { getUploadContext, uploadRoomFile } from '../../../common/uploadRoomFile.js';

export default {
	methods: {
		pickAndUpload() {
			// #ifndef MP-WEIXIN
			uni.showToast({ title: '仅支持微信小程序', icon: 'none' });
			return;
			// #endif
			// #ifdef MP-WEIXIN
			const ctx = getUploadContext();
			if (!ctx.ok) {
				uni.showToast({ title: ctx.message, icon: 'none' });
				return;
			}
			uni.chooseMessageFile({
				count: 1,
				type: 'file',
				success: (res) => {
					const f = res.tempFiles && res.tempFiles[0];
					const path = f && f.path;
					if (!path) return;
					const name = (f && f.name && String(f.name).trim()) || '';
					uploadRoomFile(path, { type: 'file', displayName: name }).catch(() => {});
				},
				fail: (err) => {
					const msg = (err && err.errMsg) || '';
					if (/cancel|取消/i.test(msg)) return;
					uni.showToast({ title: '选择文件失败', icon: 'none' });
				}
			});
			// #endif
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
.warn {
	font-size: 28rpx;
	color: #ee0a24;
}
</style>

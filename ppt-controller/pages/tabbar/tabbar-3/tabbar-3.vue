<template>
	<view class="page">
		<view class="card">
			<text class="page-title">发送到 PC</text>
			<text class="page-desc">选择文件类型，上传后 PC 端自动接收并打开</text>
		</view>
		<view class="card grid-card">
			<view class="send-grid">
				<view class="send-item" hover-class="send-item--hover" @click="onPickImage">
					<view class="send-icon send-icon--image">
						<image class="send-img" src="../../../static/img/release.png" mode="aspectFit" />
					</view>
					<text class="send-label">发图文</text>
				</view>
				<view class="send-item" hover-class="send-item--hover" @click="onPickVideo">
					<view class="send-icon send-icon--video">
						<image class="send-img" src="../../../static/img/video.png" mode="aspectFit" />
					</view>
					<text class="send-label">发视频</text>
				</view>
				<view class="send-item" hover-class="send-item--hover" @click="onPickWechatFile">
					<view class="send-icon send-icon--file">
						<image class="send-img" src="../../../static/img/qa.png" mode="aspectFit" />
					</view>
					<text class="send-label">微信文件</text>
					<!-- #ifdef MP-WEIXIN --><!-- #endif -->
				</view>
				<view class="send-item" hover-class="send-item--hover" @click="onPickPpt">
					<view class="send-icon send-icon--ppt">
						<image class="send-img" src="../../../static/img/ppt.png" mode="aspectFit" />
					</view>
					<text class="send-label">发送 PPT</text>
				</view>
			</view>
		</view>
	</view>
</template> 

<script>
import { getUploadContext, uploadRoomFile } from '../../../common/uploadRoomFile.js';

function isPptFileName(name) {
	const n = (name && String(name).trim()) || '';
	const lower = n.toLowerCase();
	return lower.endsWith('.ppt') || lower.endsWith('.pptx');
}

export default {
	data() {
		return {};
	},
	methods: {
		checkUploadReady() {
			const ctx = getUploadContext();
			if (!ctx.ok) {
				uni.showToast({ title: ctx.message, icon: 'none' });
				return false;
			}
			return true;
		},
		onPickImage() {
			if (!this.checkUploadReady()) return;
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
		},
		onPickVideo() {
			if (!this.checkUploadReady()) return;
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
		},
		onPickWechatFile() {
			// #ifndef MP-WEIXIN
			uni.showToast({ title: '仅支持微信小程序', icon: 'none' });
			// #endif
			// #ifdef MP-WEIXIN
			if (!this.checkUploadReady()) return;
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
		},
		onPickPpt() {
			// #ifndef MP-WEIXIN
			uni.showToast({ title: '仅支持微信小程序', icon: 'none' });
			// #endif
			// #ifdef MP-WEIXIN
			if (!this.checkUploadReady()) return;
			uni.chooseMessageFile({
				count: 1,
				type: 'file',
				extension: ['ppt', 'pptx'],
				success: (res) => {
					const f = res.tempFiles && res.tempFiles[0];
					const path = f && f.path;
					if (!path) return;
					const name = (f && f.name && String(f.name).trim()) || '';
					if (!isPptFileName(name)) {
						uni.showToast({ title: '请选择 .ppt 或 .pptx 文件', icon: 'none' });
						return;
					}
					uploadRoomFile(path, { type: 'ppt', displayName: name }).catch(() => {});
				},
				fail: (err) => {
					const msg = (err && err.errMsg) || '';
					if (/cancel|取消/i.test(msg)) return;
					uni.showToast({ title: '选择 PPT 失败', icon: 'none' });
				}
			});
			// #endif
		}
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

.page-title {
	display: block;
	font-size: 32rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 10rpx;
}

.page-desc {
	display: block;
	font-size: 24rpx;
	color: #999;
	line-height: 1.5;
}

.grid-card {
	padding: 20rpx;
}

.send-grid {
	display: flex;
	flex-wrap: wrap;
	gap: 20rpx;
}

.send-item {
	flex: 1;
	min-width: calc(50% - 10rpx);
	max-width: calc(50% - 10rpx);
	display: flex;
	flex-direction: column;
	align-items: center;
	padding: 36rpx 20rpx;
	background: #f8f8f8;
	border-radius: 16rpx;
	box-sizing: border-box;
}

.send-item--hover {
	background: #f0f0f0;
}

.send-icon {
	width: 96rpx;
	height: 96rpx;
	border-radius: 24rpx;
	display: flex;
	align-items: center;
	justify-content: center;
	margin-bottom: 16rpx;
}

.send-icon--image { background: linear-gradient(145deg, #e3f2fd, #bbdefb); }
.send-icon--video { background: linear-gradient(145deg, #f3e5f5, #e1bee7); }
.send-icon--file  { background: linear-gradient(145deg, #e8f5e9, #c8e6c9); }
.send-icon--ppt   { background: linear-gradient(145deg, #fff3e0, #ffe0b2); }

.send-img {
	width: 56rpx;
	height: 56rpx;
}

.send-label {
	font-size: 26rpx;
	color: #333;
	font-weight: 500;
}
</style>

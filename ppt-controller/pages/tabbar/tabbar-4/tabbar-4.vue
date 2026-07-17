<template>
	<view class="page">
		<view class="toolbar card">
			<text class="toolbar-title">发送记录</text>
			<text v-if="records.length" class="toolbar-clear" @click="onClearAll">清空</text>
		</view>

		<view v-if="!records.length" class="empty card">
			<text class="empty-icon">📤</text>
			<text class="empty-title">暂无发送记录</text>
			<text class="empty-desc">在「发送到 PC」中上传图片、视频或文件后，将在此显示时间与房间等信息</text>
		</view>

		<scroll-view v-else class="list-scroll" scroll-y :show-scrollbar="true">
			<view
				v-for="r in records"
				:key="r.id"
				class="record card"
				:class="'record--' + r.status"
			>
				<view class="record-icon" :class="'record-icon--' + r.type">
					<text class="record-icon-txt">{{ typeIcon(r.type) }}</text>
				</view>
				<view class="record-body">
					<text class="record-name">{{ r.displayName }}</text>
					<text class="record-meta">
						{{ formatTime(r.time) }} · 房间 {{ r.roomId || '—' }} · {{ r.status === 'success' ? '成功' : '失败' }}
					</text>
					<text v-if="r.status === 'fail' && r.detail" class="record-detail">{{ r.detail }}</text>
			</view>
			<view v-if="r.status === 'fail'" class="record-retry" @click="onRetry">重新发送</view>
			</view>
			<view class="list-footer" />
		</scroll-view>
	</view>
</template>

<script>
import {
	getSendRecords,
	clearSendRecords,
	markSendRecordsTabSeen
} from '../../../common/uploadRoomFile.js';

export default {
	data() {
		return {
			records: []
		};
	},
	onShow() {
		this.refresh();
		markSendRecordsTabSeen();
	},
	methods: {
		refresh() {
			this.records = getSendRecords();
		},
		typeIcon(type) {
			if (type === 'image') return '🖼';
			if (type === 'video') return '🎬';
			if (type === 'ppt') return '📊';
			return '📎';
		},
		formatTime(ts) {
			const d = new Date(typeof ts === 'number' ? ts : Number(ts) || Date.now());
			const pad = (n) => (n < 10 ? `0${n}` : `${n}`);
			return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
				d.getMinutes()
			)}`;
		},
		onRetry() {
				uni.switchTab({ url: '/pages/tabbar/tabbar-3/tabbar-3' });
			},
			onClearAll() {
			if (!this.records.length) return;
			uni.showModal({
				title: '清空记录',
				content: '确定清空全部发送记录？此操作不可恢复。',
				confirmColor: '#f33e54',
				success: (res) => {
					if (res.confirm) {
						clearSendRecords();
						this.refresh();
						uni.showToast({ title: '已清空', icon: 'success' });
					}
				}
			});
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

.toolbar {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding-top: 20rpx;
	padding-bottom: 20rpx;
}

.toolbar-title {
	font-size: 32rpx;
	font-weight: 600;
	color: #333;
}

.toolbar-clear {
	font-size: 28rpx;
	color: #f33e54;
	font-weight: 500;
}

.empty {
	display: flex;
	flex-direction: column;
	align-items: center;
	text-align: center;
	padding: 64rpx 40rpx 80rpx;
}

.empty-icon {
	font-size: 88rpx;
	line-height: 1.2;
	margin-bottom: 24rpx;
	opacity: 0.85;
}

.empty-title {
	font-size: 30rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 16rpx;
}

.empty-desc {
	font-size: 26rpx;
	color: #888;
	line-height: 1.55;
	max-width: 560rpx;
}

.list-scroll {
	max-height: calc(100vh - 200rpx);
}

.list-footer {
	height: 24rpx;
}

.record {
	display: flex;
	flex-direction: row;
	align-items: flex-start;
	gap: 20rpx;
	padding: 24rpx 28rpx;
}

.record-icon {
	width: 88rpx;
	height: 88rpx;
	border-radius: 20rpx;
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
}

.record-icon--image {
	background: linear-gradient(145deg, #e3f2fd, #bbdefb);
}

.record-icon--video {
	background: linear-gradient(145deg, #f3e5f5, #e1bee7);
}

.record-icon--file {
	background: linear-gradient(145deg, #e8f5e9, #c8e6c9);
}

.record-icon--ppt {
	background: linear-gradient(145deg, #fff3e0, #ffe0b2);
}

.record-icon-txt {
	font-size: 40rpx;
	line-height: 1;
}

.record-body {
	flex: 1;
	min-width: 0;
}

.record-name {
	display: block;
	font-size: 28rpx;
	font-weight: 600;
	color: #333;
	margin-bottom: 10rpx;
	word-break: break-all;
}

.record-meta {
	display: block;
	font-size: 24rpx;
	color: #888;
	line-height: 1.45;
}

.record--fail .record-meta {
	color: #c62828;
}

.record-retry {
	font-size: 24rpx;
	color: #f33e54;
	font-weight: 500;
	padding: 8rpx 16rpx;
	border: 1rpx solid #f33e54;
	border-radius: 8rpx;
	flex-shrink: 0;
	align-self: center;
	margin-left: 12rpx;
}

.record-detail {
	display: block;
	font-size: 22rpx;
	color: #999;
	margin-top: 8rpx;
	line-height: 1.4;
	word-break: break-all;
}
</style>

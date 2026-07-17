package com.dilikes.pptcontroller.controller;

import com.dilikes.pptcontroller.config.FileConfig;
import com.dilikes.pptcontroller.config.RoomManager;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.io.*;
import java.net.URLEncoder;
import java.util.UUID;

@RestController
@RequestMapping("/file")
public class FileController {

    @Autowired
    private FileConfig fileConfig;

    /**
     * 手机上传文件，存入对应房间目录
     */
    @PostMapping("/upload")
    public String upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam("roomId") String roomId
    ) throws Exception {

        String originalFilename = file.getOriginalFilename();
        String uuid = UUID.randomUUID().toString().replace("-", "");
        String storeName = uuid + "_" + originalFilename;

        // 重点：按房间创建目录
        String roomDir = fileConfig.getRoomDir(roomId);
        File destFile = new File(roomDir, storeName);
        file.transferTo(destFile);

        // 构造下载URI
        String downloadUri = "/file/download/" + roomId + "/" + storeName;

        // ======================
        // 关键：上传完立刻推送给对应房间的Python
        // ======================
        String msg = "{\"cmd\":\"FILE_ARRIVED\",\"url\":\"" + downloadUri + "\"}";
        RoomManager.forwardToTarget(roomId, msg);

        return "success";
    }

    /**
     * 按房间下载文件（强隔离）
     */
    @GetMapping("/download/{roomId}/{fileName}")
    public void download(
            @PathVariable String roomId,
            @PathVariable String fileName,
            HttpServletResponse response
    ) throws Exception {

        String roomDir = fileConfig.getRoomDir(roomId);
        File file = new File(roomDir, fileName);

        if (!file.exists()) {
            response.sendError(404);
            return;
        }

        response.setContentType("application/octet-stream");
        response.setHeader("Content-Disposition",
                "attachment;filename=" + URLEncoder.encode(fileName, "UTF-8"));

        try (InputStream in = new FileInputStream(file);
             OutputStream out = response.getOutputStream()) {

            byte[] buf = new byte[8192];
            int len;
            while ((len = in.read(buf)) != -1) {
                out.write(buf, 0, len);
            }
            out.flush();
        }
    }
}

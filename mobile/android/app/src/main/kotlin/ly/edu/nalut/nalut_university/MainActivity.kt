package ly.edu.nalut.nalut_university

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.ContentResolver
import android.content.Intent
import android.media.AudioAttributes
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createChannels()
    }

    // One channel per level of urgency, each with its own tone. The server sends every push to
    // one of these ids. Android keeps a channel's sound once created, so the user changes a tone
    // from the system settings (openChannelSettings below), and new tones need new channel ids.
    private fun createChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.deleteNotificationChannel("nus_alerts") // the single channel of the first release
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        val channels = listOf(
            Triple("nus_normal", "الإعلانات العادية", R.raw.tone_normal),
            Triple("nus_important", "الإشعارات المهمة", R.raw.tone_important),
            Triple("nus_urgent", "التنبيهات العاجلة والإنذارات", R.raw.tone_urgent),
        )
        for ((id, name, tone) in channels) {
            val channel = NotificationChannel(id, name, NotificationManager.IMPORTANCE_HIGH).apply {
                description = "إشعارات منصة الجامعة"
                enableVibration(true)
                if (id == "nus_urgent") vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
                setSound(Uri.parse("${ContentResolver.SCHEME_ANDROID_RESOURCE}://$packageName/$tone"), attributes)
            }
            manager.createNotificationChannel(channel)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "nus/notifications").setMethodCallHandler { call, result ->
            when (call.method) {
                "openChannelSettings" -> {
                    val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                            .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                            .putExtra(Settings.EXTRA_CHANNEL_ID, call.argument<String>("channel"))
                    } else {
                        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
                    }
                    startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    result.success(true)
                }
                else -> result.notImplemented()
            }
        }
    }
}

package ly.edu.nalut.nalut_university

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.ContentResolver
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    // The tones bundled in res/raw. The university administration chooses which one each kind
    // of notification uses, and the server sends every push to channel "nus_tone_<name>".
    private val tones = linkedMapOf(
        "chime" to Pair(R.raw.tone_chime, "جرس هادئ"),
        "bell" to Pair(R.raw.tone_bell, "جرس"),
        "rising" to Pair(R.raw.tone_rising, "ثلاث نغمات صاعدة"),
        "pulse" to Pair(R.raw.tone_pulse, "نبضتان"),
        "alarm" to Pair(R.raw.tone_alarm, "إنذار متكرر"),
        "siren" to Pair(R.raw.tone_siren, "تنبيه حاد"),
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createChannels()
    }

    private fun toneUri(res: Int) = Uri.parse("${ContentResolver.SCHEME_ANDROID_RESOURCE}://$packageName/$res")

    private fun createChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        // channels of earlier releases
        for (old in listOf("nus_alerts", "nus_normal", "nus_important", "nus_urgent")) {
            manager.deleteNotificationChannel(old)
        }
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        for ((name, tone) in tones) {
            val channel = NotificationChannel("nus_tone_$name", "إشعارات الجامعة — ${tone.second}",
                NotificationManager.IMPORTANCE_HIGH).apply {
                description = "تحدد إدارة الجامعة أي نوع من الإشعارات يستخدم هذه النغمة"
                enableVibration(true)
                if (name == "alarm" || name == "siren") vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
                setSound(toneUri(tone.first), attributes)
            }
            manager.createNotificationChannel(channel)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "nus/notifications").setMethodCallHandler { call, result ->
            when (call.method) {
                // the system plays nothing for a push that arrives while the app is open
                "playTone" -> {
                    val tone = tones[call.argument<String>("tone")] ?: tones.getValue("chime")
                    RingtoneManager.getRingtone(applicationContext, toneUri(tone.first))?.play()
                    result.success(true)
                }
                "openAppSettings" -> {
                    val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
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

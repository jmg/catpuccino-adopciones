from django.core.management.base import BaseCommand, CommandError
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as wait
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import requests
import re
import json
from bs4 import BeautifulSoup


class Command(BaseCommand):

    def handle(self, *args, **options):

        url = "https://www.instagram.com/p/Cq6AYP9rCob/?img_index={}".format(1)

        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        service = Service(executable_path="/usr/lib/chromium-browser/chromedriver")
        driver = webdriver.Chrome(service=service, options=options)
        driver.get(url)
        #wait
        try:
            wait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "FFVAD")))
        except:
            pass
        scripts = driver.find_elements(By.XPATH, "//script")

        open("test.html", "w").write(driver.page_source)

        for script in scripts:

            content = script.get_attribute("innerHTML")

            try:
                print (content[0:100])
                json_data = json.loads(str(content))
                import ipdb; ipdb.set_trace()
            except:
                pass

        #print (images)